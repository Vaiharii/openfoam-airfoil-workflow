"""High-level workflow orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .airfoil import prepare_geometry
from .config import WorkflowConfig
from .files import (
    copytree_clean,
    ensure_dir,
    marker_exists,
    read_json,
    remove_markers,
    touch,
    write_json,
)
from .mesh_quality import (
    adjust_mesh_parameters,
    mesh_check_is_acceptable,
    mesh_check_reason,
    parse_check_mesh_log,
)
from .openfoam import (
    enrich_sample,
    solver_commands,
    write_allrun_mesh,
    write_allrun_solver,
    write_case_dictionaries,
    write_slurm_script,
)
from .post import postprocess
from .runner import CommandRunner
from .sampling import generate_samples, read_sampling_csv, write_sampling_files
from .stl_analysis import analyze_stl, apply_stl_mesh_estimate


CASE_FINGERPRINT_SECTIONS = (
    "airfoil",
    "geometry",
    "output",
    "base_case",
    "domain",
    "snappy",
    "snap",
    "layers",
    "distance_refinement",
    "local_refinement",
    "mesh_estimation",
    "mesh",
    "mesh_auto",
    "sampling",
    "reference",
    "execution",
    "control",
    "functions",
)

POST_FINGERPRINT_SECTIONS = CASE_FINGERPRINT_SECTIONS + ("post",)
GENERATOR_VERSION = "openfoam-dicts-v4-stl-adaptive-mesh"


class AirfoilWorkflow:
    def __init__(
        self,
        cfg: WorkflowConfig,
        dry_run: bool = False,
        force: bool = False,
        execute_openfoam: bool | None = None,
    ):
        self.cfg = cfg
        self.dry_run = dry_run
        self.force = force
        self.execute_openfoam = execute_openfoam
        self.runner = CommandRunner(cfg, dry_run=dry_run)
        self._geometry: dict[str, Any] | None = None

    @property
    def study_dir(self) -> Path:
        return self.cfg.study_dir

    @property
    def mesh_reference_dir(self) -> Path:
        return self.study_dir / self.cfg.get("mesh", "reference_case_name", fallback="_mesh_reference")

    def _stage_execute_enabled(self, section: str) -> bool:
        if self.execute_openfoam is not None:
            return self.execute_openfoam
        mode = self.cfg.get("execution", "mode", fallback="prepare_only").lower()
        if mode == "prepare_only":
            return False
        section_enabled = self.cfg.get_bool(section, "execute", fallback=False)
        global_enabled = self.cfg.get_bool("execution", "execute", fallback=False)
        return section_enabled and global_enabled

    def geometry(self) -> dict[str, Any]:
        print("\n[geometry] Preparing airfoil STL")
        self._geometry = prepare_geometry(self.cfg, force=self.force)
        print(f"[geometry] Airfoil: {self._geometry['airfoil_name']}")
        print(f"[geometry] STL: {self._geometry['canonical_stl']}")
        return self._geometry

    def mesh(self) -> Path:
        print("\n[mesh] Preparing reference mesh case")
        ensure_dir(self.study_dir)
        mesh_force = self.force or self.cfg.get_bool("mesh", "force", fallback=False)
        mesh_execute = self._stage_execute_enabled("mesh")
        geometry: dict[str, Any] | None = None
        stl_analysis = None
        estimate_notes: list[str] = []
        if self.cfg.get_bool("mesh_auto", "estimate_from_stl", fallback=True):
            geometry = self._geometry or self.geometry()
            stl_analysis = analyze_stl(Path(geometry["canonical_stl"]))
            estimate_notes = apply_stl_mesh_estimate(self.cfg, stl_analysis)
        if not mesh_force and self._mesh_state_is_current():
            if marker_exists(self.mesh_reference_dir, ".meshdone"):
                print(f"[mesh] Marker found, skipping: {self.mesh_reference_dir / '.meshdone'}")
                return self.mesh_reference_dir
            if marker_exists(self.mesh_reference_dir, ".meshprepared") and not mesh_execute:
                print(f"[mesh] Prepared marker found, skipping: {self.mesh_reference_dir / '.meshprepared'}")
                return self.mesh_reference_dir

        geometry = geometry or self._geometry or self.geometry()
        template_dir = self.cfg.get_path("base_case", "template_dir")
        assert template_dir is not None
        if not template_dir.is_dir():
            raise FileNotFoundError(f"Base case template not found: {template_dir}")

        if self.mesh_reference_dir.exists():
            remove_markers(self.mesh_reference_dir)
        copytree_clean(template_dir, self.mesh_reference_dir, force=mesh_force)
        ensure_dir(self.mesh_reference_dir / "constant" / "triSurface")
        shutil.copy2(geometry["canonical_stl"], self.mesh_reference_dir / "constant" / "triSurface" / "geometry.stl")

        if self.cfg.get_bool("mesh_auto", "estimate_from_stl", fallback=True):
            assert stl_analysis is not None
            write_json(
                self.mesh_reference_dir / "mesh_estimate.json",
                {
                    "stl": stl_analysis.to_dict(),
                    "applied_parameters": estimate_notes,
                },
            )
            print(
                "[mesh:auto] STL estimate: "
                f"triangles={stl_analysis.triangle_count}, "
                f"chord={stl_analysis.chord:.6g}, "
                f"span={stl_analysis.span:.6g}"
            )
            for note in estimate_notes:
                print(f"[mesh:auto] {note}")

        sample = generate_samples(self.cfg)[0]
        write_case_dictionaries(self.mesh_reference_dir, self.cfg, sample)
        write_allrun_mesh(self.mesh_reference_dir, self.cfg)
        write_allrun_solver(self.mesh_reference_dir, self.cfg)
        self._write_mesh_state(geometry, stage="prepared")

        if not mesh_execute:
            touch(self.mesh_reference_dir / ".meshprepared")
            print("[mesh] Prepared only. Set mesh.execute/execution.execute or use --execute-openfoam to run.")
            return self.mesh_reference_dir

        commands = self.cfg.get_list("mesh", "commands", cast=str)
        max_attempts = 1
        if self.cfg.get_bool("mesh_auto", "enabled", fallback=False):
            max_attempts = self.cfg.get_int("mesh_auto", "max_attempts", fallback=1)
        unlimited_attempts = max_attempts <= 0
        history: list[dict[str, Any]] = []
        accepted = False
        attempt = 1
        while unlimited_attempts or attempt <= max_attempts:
            if attempt > 1:
                self._clean_mesh_outputs(self.mesh_reference_dir)
                write_case_dictionaries(self.mesh_reference_dir, self.cfg, sample)
                write_allrun_mesh(self.mesh_reference_dir, self.cfg)
                write_allrun_solver(self.mesh_reference_dir, self.cfg)

            attempts_label = "∞" if unlimited_attempts else str(max_attempts)
            print(f"[mesh] Attempt {attempt}/{attempts_label}")
            failed_command: dict[str, Any] | None = None
            check_log: Path | None = None
            for index, command in enumerate(commands, start=1):
                log_name = f"log.mesh.{index:02d}" if max_attempts == 1 else f"log.mesh.attempt{attempt:02d}.{index:02d}"
                result = self.runner.run(command, self.mesh_reference_dir, log_name)
                if command.strip().startswith("checkMesh"):
                    check_log = result.log_path
                if result.returncode != 0:
                    failed_command = {
                        "command": command,
                        "returncode": result.returncode,
                        "log_path": str(result.log_path),
                    }
                    break

            if self.dry_run:
                touch(self.mesh_reference_dir / ".meshprepared")
                print("[mesh] Dry-run command plan written; not marking .meshdone.")
                return self.mesh_reference_dir

            check_result = parse_check_mesh_log(check_log) if check_log is not None and check_log.exists() else None
            history_item: dict[str, Any] = {
                "attempt": attempt,
                "failed_command": failed_command,
                "checkMesh": check_result.to_dict() if check_result else None,
                "local_refinement_boxes": self.cfg.get("local_refinement", "boxes", fallback=""),
            }
            history.append(history_item)
            write_json(self.mesh_reference_dir / "mesh_attempts.json", history)

            if failed_command is None and mesh_check_is_acceptable(self.cfg, check_result):
                accepted = True
                print(f"[mesh] Accepted: {mesh_check_reason(self.cfg, check_result)}")
                break

            reason = mesh_check_reason(self.cfg, check_result)
            if failed_command is not None:
                reason = f"{failed_command['command']} failed with code {failed_command['returncode']}; {reason}"
            print(f"[mesh] Rejected attempt {attempt}: {reason}")
            if not unlimited_attempts and attempt == max_attempts:
                log_hint = check_log or (Path(failed_command["log_path"]) if failed_command else self.mesh_reference_dir)
                raise RuntimeError(f"Mesh did not meet quality targets after {max_attempts} attempt(s). See {log_hint}")

            notes = adjust_mesh_parameters(
                self.cfg,
                check_result,
                attempt,
                case_dir=self.mesh_reference_dir,
                stl_analysis=stl_analysis,
            )
            for note in notes:
                print(f"[mesh:auto] {note}")
            if len(notes) == 1 and notes[0].startswith("No obvious automatic mesh change"):
                raise RuntimeError("Mesh automation cannot make further progress from the available diagnostics.")
            attempt += 1

        if not accepted:
            raise RuntimeError("Mesh automation ended without an accepted mesh.")
        touch(self.mesh_reference_dir / ".meshdone")
        self._write_mesh_state(geometry, stage="meshdone")
        print("[mesh] Mesh completed")
        return self.mesh_reference_dir

    def sample(self, assume_stale: bool = False) -> list[dict[str, Any]]:
        print("\n[sampling] Generating case directories")
        ensure_dir(self.study_dir)
        if (
            not assume_stale
            and marker_exists(self.study_dir, ".samplingdone")
            and not self.force
            and self._sampling_is_current()
        ):
            print(f"[sampling] Marker found, reading existing sampling: {self.study_dir / 'sampling.csv'}")
            return read_sampling_csv(self.study_dir / "sampling.csv")

        if not self.mesh_reference_dir.exists():
            self.mesh()

        geometry = self._geometry or self.geometry()
        samples = generate_samples(self.cfg)
        for sample in samples:
            case_dir = self.study_dir / sample["case_id"]
            copytree_clean(self.mesh_reference_dir, case_dir, force=True)
            remove_markers(case_dir)
            write_case_dictionaries(case_dir, self.cfg, sample)
            write_allrun_mesh(case_dir, self.cfg)
            write_allrun_solver(case_dir, self.cfg)
            shutil.copy2(geometry["canonical_stl"], case_dir / "constant" / "triSurface" / "geometry.stl")
            touch(case_dir / ".caseprepared")

        write_sampling_files(self.study_dir, samples, self.cfg, geometry, self._case_fingerprint())
        touch(self.study_dir / ".samplingdone")
        print(f"[sampling] Created {len(samples)} case(s) in {self.study_dir}")
        return samples

    def run(self) -> None:
        print("\n[run] Preparing simulation execution")
        mode = self.cfg.get("execution", "mode", fallback="prepare_only").lower()
        execute = self._stage_execute_enabled("execution")
        if not self.force and self._sampling_is_current():
            if marker_exists(self.study_dir, ".runsdone"):
                print(f"[run] Marker found, skipping: {self.study_dir / '.runsdone'}")
                return
            if marker_exists(self.study_dir, ".runprepared") and not execute:
                print(f"[run] Prepared marker found, skipping: {self.study_dir / '.runprepared'}")
                return

        samples = self._samples_for_run()
        effective_mode = "local" if execute and mode == "prepare_only" else mode

        if effective_mode == "local" and execute:
            self._run_local_cases(samples)
            if self.dry_run:
                touch(self.study_dir / ".runprepared")
                print("[run] Dry-run command plan written; not marking .runsdone.")
            else:
                touch(self.study_dir / ".runsdone")
                print("[run] Simulations completed")
            return

        for sample in samples:
            case_dir = self.study_dir / sample["case_id"]
            write_allrun_solver(case_dir, self.cfg)
            if effective_mode == "slurm":
                script = write_slurm_script(case_dir, self.cfg, sample)
                if execute and self.cfg.get_bool("slurm", "submit", fallback=False):
                    result = self.runner.run(f"sbatch {script.name}", case_dir, "log.sbatch")
                    if result.returncode != 0:
                        self._mark_case_failed(case_dir)
                        if self.cfg.get_bool("execution", "stop_on_error", fallback=True):
                            raise RuntimeError(f"SLURM submission failed for {case_dir}. See {result.log_path}")
                    else:
                        touch(case_dir / ".submitted")
                continue

        if not execute:
            touch(self.study_dir / ".runprepared")
            print("[run] Prepared run scripts only. Use --execute-openfoam or enable execution in INI.")
            return

        if effective_mode == "slurm":
            touch(self.study_dir / ".submitted")
            print("[run] SLURM scripts prepared/submitted; not marking .runsdone.")
        else:
            touch(self.study_dir / ".runsdone")
            print("[run] Simulations completed")

    def post(self) -> dict[str, Any]:
        print("\n[post] Collecting post-processing outputs")
        post_force = self.force or self.cfg.get_bool("post", "force", fallback=False)
        if marker_exists(self.cfg.results_dir, ".postdone") and not post_force and self._post_state_is_current():
            print(f"[post] Marker found, skipping: {self.cfg.results_dir / '.postdone'}")
            return {"results_dir": str(self.cfg.results_dir), "skipped": True}
        if not (self.study_dir / "sampling.csv").is_file():
            self.sample()
        summary = postprocess(self.study_dir, self.cfg.results_dir)
        self._write_post_state()
        touch(self.cfg.results_dir / ".postdone")
        print(f"[post] Results written to {self.cfg.results_dir}")
        return summary

    def _samples_for_run(self) -> list[dict[str, Any]]:
        sampling_path = self.study_dir / "sampling.csv"
        if not sampling_path.is_file():
            return self.sample()
        if not self._sampling_is_current(announce=False):
            return self.sample(assume_stale=True)
        samples = []
        for row in read_sampling_csv(sampling_path):
            samples.append(enrich_sample(row, self.cfg))
        if any(not self._case_is_prepared(sample["case_id"]) for sample in samples):
            return self.sample()
        return samples

    @staticmethod
    def _mark_case_failed(case_dir: Path) -> None:
        touch(case_dir / ".casefailed")

    @staticmethod
    def _clean_mesh_outputs(case_dir: Path) -> None:
        for child in case_dir.iterdir() if case_dir.exists() else []:
            if child.name.startswith("processor") or child.name == "postProcessing":
                if child.is_dir():
                    shutil.rmtree(child)
                elif child.exists():
                    child.unlink()
                continue
            try:
                float(child.name)
            except ValueError:
                continue
            if child.is_dir():
                shutil.rmtree(child)
        for rel in ("constant/polyMesh", "constant/extendedFeatureEdgeMesh"):
            path = case_dir / rel
            if path.exists():
                shutil.rmtree(path)
        tri_surface = case_dir / "constant" / "triSurface"
        if tri_surface.exists():
            for feature_file in tri_surface.glob("*.eMesh"):
                feature_file.unlink()
        remove_markers(case_dir)

    def _run_local_cases(self, samples: list[dict[str, Any]]) -> None:
        max_workers = max(1, self.cfg.get_int("execution", "max_workers", fallback=1))
        if max_workers == 1:
            for sample in samples:
                self._run_local_case(sample)
            return

        print(f"[run] Launching local cases with max_workers={max_workers}")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._run_local_case, sample): sample for sample in samples}
            for future in as_completed(futures):
                sample = futures[future]
                try:
                    future.result()
                except Exception:
                    if self.cfg.get_bool("execution", "stop_on_error", fallback=True):
                        raise
                    print(f"[run] Case failed and stop_on_error=false: {sample['case_id']}")

    def _run_local_case(self, sample: dict[str, Any]) -> None:
        case_dir = self.study_dir / sample["case_id"]
        write_allrun_solver(case_dir, self.cfg)
        ok = True
        for index, command in enumerate(solver_commands(self.cfg), start=1):
            result = self.runner.run(command, case_dir, f"log.run.{index:02d}")
            if result.returncode != 0:
                ok = False
                self._mark_case_failed(case_dir)
                if self.cfg.get_bool("execution", "stop_on_error", fallback=True):
                    raise RuntimeError(
                        f"Simulation command failed ({result.returncode}) in {case_dir}: "
                        f"{command}. See {result.log_path}"
                    )
                break
        if ok and not self.dry_run:
            touch(case_dir / ".casedone")

    def _mesh_state_is_current(self) -> bool:
        state_path = self.mesh_reference_dir / "workflow_state.json"
        if not state_path.is_file():
            return False
        try:
            state = read_json(state_path)
        except Exception:
            return False
        return state.get("config_fingerprint") == self._case_fingerprint()

    def _write_mesh_state(self, geometry: dict[str, Any], stage: str) -> None:
        write_json(
            self.mesh_reference_dir / "workflow_state.json",
            {
                "stage": stage,
                "config_fingerprint": self._case_fingerprint(),
                "geometry": geometry,
            },
        )

    def _sampling_is_current(self, announce: bool = True) -> bool:
        sampling_path = self.study_dir / "sampling.csv"
        campaign_path = self.study_dir / "campaign.json"
        if not sampling_path.is_file() or not campaign_path.is_file():
            return False
        try:
            campaign = read_json(campaign_path)
        except Exception:
            return False
        if campaign.get("config_fingerprint") != self._case_fingerprint():
            if announce:
                print("[sampling] Configuration changed since campaign generation; regenerating.")
            return False
        samples = read_sampling_csv(sampling_path)
        if not samples:
            return False
        return all(self._case_is_prepared(sample["case_id"]) for sample in samples)

    def _case_is_prepared(self, case_id: str) -> bool:
        case_dir = self.study_dir / case_id
        required = (
            case_dir / ".caseprepared",
            case_dir / "0" / "U",
            case_dir / "0" / "p",
            case_dir / "constant" / "transportProperties",
            case_dir / "constant" / "turbulenceProperties",
            case_dir / "constant" / "triSurface" / "geometry.stl",
            case_dir / "system" / "controlDict",
            case_dir / "system" / "fvSchemes",
            case_dir / "system" / "fvSolution",
            case_dir / "Allrun",
        )
        if not all(path.exists() for path in required):
            return False
        if marker_exists(self.mesh_reference_dir, ".meshdone"):
            return (case_dir / "constant" / "polyMesh" / "boundary").is_file()
        return True

    def _post_state_is_current(self) -> bool:
        state_path = self.cfg.results_dir / "workflow_state.json"
        if not state_path.is_file():
            return False
        try:
            state = read_json(state_path)
        except Exception:
            return False
        return state.get("config_fingerprint") == self._post_fingerprint()

    def _write_post_state(self) -> None:
        write_json(
            self.cfg.results_dir / "workflow_state.json",
            {
                "config_fingerprint": self._post_fingerprint(),
                "study": self.cfg.study_name,
            },
        )

    def _case_fingerprint(self) -> str:
        return f"{GENERATOR_VERSION}:{self._policy_fingerprint(CASE_FINGERPRINT_SECTIONS)}"

    def _post_fingerprint(self) -> str:
        return f"{GENERATOR_VERSION}:{self._policy_fingerprint(POST_FINGERPRINT_SECTIONS)}"

    def _policy_fingerprint(self, sections: tuple[str, ...]) -> str:
        payload = {
            section: values
            for section, values in self.cfg.as_dict().items()
            if section in set(sections)
        }
        if self.cfg.get_bool("mesh_auto", "estimate_from_stl", fallback=True):
            payload.pop("domain", None)
            _drop_options(
                payload,
                "snappy",
                {
                    "location_in_mesh",
                    "max_global_cells",
                    "max_local_cells",
                    "n_cells_between_levels",
                    "surface_level_min",
                    "surface_level_max",
                    "feature_level",
                },
            )
            _drop_options(payload, "distance_refinement", {"levels"})
            _drop_options(payload, "snap", {"n_smooth_patch", "n_solve_iter", "n_relax_iter"})
        _drop_options(payload, "local_refinement", {"boxes"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _drop_options(payload: dict[str, dict[str, str]], section: str, options: set[str]) -> None:
    values = payload.get(section)
    if not values:
        return
    for option in options:
        values.pop(option, None)
