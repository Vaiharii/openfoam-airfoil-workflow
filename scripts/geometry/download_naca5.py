#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
date: 06-21-2026
author: @vpagnacco

description:
    Download pure NACA 5-digit airfoil .dat files from the UIUC airfoil database.

    The script looks for files named like:
        naca23012.dat
        naca23015.dat
        naca23018.dat
        naca23021.dat
        naca23024.dat

    On the UIUC database, the detected pure NACA 5-digit files are currently
    limited to the NACA 230xx family.

    All downloaded files are saved with a normalized name:
        nacaXXXXX.dat
"""

from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urljoin

BASE_URL = "https://m-selig.ae.illinois.edu/ads/coord_database.html"
OUTPUT_DIR = Path("airfoils/database/naca5")

def read_web_page(url):
    """
    Read the content of a web page.

    Parameters
    ----------
    url : str
        Web page URL.

    Returns
    -------
    str
        HTML content of the web page.
    """
    print()
    print("=" * 80)
    print("READ WEB PAGE")
    print("=" * 80)
    print(f"URL = {url}")
    with urlopen(url) as response:
        content = response.read()
    html = content.decode("utf-8", errors="ignore")
    print(f"HTML size = {len(html)} characters")

    return html

def is_naca5_file(filename):
    """
    Check if a filename corresponds to a pure NACA 5-digit .dat file.

    Accepted examples:
        naca23012.dat
        naca23015.dat
        naca23018.dat
        naca23021.dat
        naca23024.dat

    Rejected examples:
        naca16006.dat
        naca16009.dat
        naca16012.dat
        naca16015.dat
        naca16018.dat
        naca16021.dat

    These rejected examples contain five digits after 'naca', but they belong
    to the NACA 16-series, not to the classical NACA 5-digit family.

    Parameters
    ----------
    filename : str
        Name of the file.

    Returns
    -------
    bool
        True if the file is a pure NACA 5-digit .dat file.
    """
    filename = filename.lower()
    if not filename.endswith(".dat"):
        return False
    name = filename.replace(".dat", "")
    if not name.startswith("naca"):
        return False
    digits = name[4:]
    if not (len(digits) == 5 and digits.isdigit()):
        return False
    answer = digits.startswith("230")
    if answer:
        print(f"Found NACA5 file : {filename}")

    return answer

def normalize_naca5_filename(filename):
    """
    Normalize a pure NACA 5-digit filename.

    Examples
    --------
    naca23012.dat -> naca23012.dat
    naca23015.dat -> naca23015.dat

    Parameters
    ----------
    filename : str
        Original filename.

    Returns
    -------
    str
        Normalized filename.
    """
    filename = filename.lower()
    name = filename.replace(".dat", "")
    digits = name[4:]

    return f"naca{digits}.dat"

def extract_links_from_html(html):
    """
    Extract all links from an HTML page.

    This is a simple parser based on href="...".
    It is sufficient for the UIUC airfoil database page.

    Parameters
    ----------
    html : str
        HTML content.

    Returns
    -------
    list[str]
        List of detected links.
    """
    print()
    print("=" * 80)
    print("EXTRACT LINKS")
    print("=" * 80)
    links = []
    parts = html.split("href=")
    print(f"Number of href= found : {len(parts)-1}")
    for part in parts[1:]:
        if part.startswith('"'):
            link = part.split('"')[1]
        elif part.startswith("'"):
            link = part.split("'")[1]
        else:
            link = part.split(">")[0].split()[0]
        links.append(link)
    print(f"Number of links extracted : {len(links)}")

    return links

def get_naca5_files():
    """
    Find all pure NACA 5-digit .dat files listed on the UIUC database page.

    Returns
    -------
    list[tuple[str, str]]
        List of tuples containing:
            - normalized filename
            - download URL
    """
    print()
    print("=" * 80)
    print("SEARCH NACA5 FILES")
    print("=" * 80)
    html = read_web_page(BASE_URL)
    links = extract_links_from_html(html)
    files = []
    for link in links:
        filename = Path(link).name
        if is_naca5_file(filename):
            output_name = normalize_naca5_filename(filename)
            download_url = urljoin(BASE_URL, link)
            print()
            print(f"Original name   : {filename}")
            print(f"Normalized name : {output_name}")
            print(f"URL             : {download_url}")
            files.append((output_name, download_url))
    files = sorted(set(files))
    print()
    print(f"Total number of NACA5 files found : {len(files)}")

    return files

def download_file(url, output_path):
    """
    Download a file and save it locally.

    Parameters
    ----------
    url : str
        File URL.

    output_path : Path | str
        Local output path.

    Returns
    -------
    None
    """
    print()
    print("-" * 80)
    print("DOWNLOAD FILE")
    print("-" * 80)
    print(f"URL         : {url}")
    print(f"Output file : {output_path}")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url) as response:
        content = response.read()
    output_path.write_bytes(content)
    print("Done.")

def download_naca5_files():
    """
    Download all detected pure NACA 5-digit files.

    Returns
    -------
    None
    """
    print()
    print("#" * 80)
    print("DOWNLOAD ALL NACA5 FILES")
    print("#" * 80)
    files = get_naca5_files()
    print()
    print(f"{len(files)} files detected")
    print(f"Detected {len(files)} pure NACA 5-digit files.")
    for i, (filename, url) in enumerate(files):
        print()
        print("#" * 80)
        print(f"FILE {i+1}/{len(files)}")
        print("#" * 80)
        output_path = OUTPUT_DIR / filename
        if output_path.exists():
            print(f"{filename} already exists.")
            print("Skip.")
            continue
        print(f"Download: {filename}")
        download_file(url, output_path)
    print()
    print("#" * 80)
    print("END OF DOWNLOAD")
    print("#" * 80)

if __name__ == "__main__":
    download_naca5_files()