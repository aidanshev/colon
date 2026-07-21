#!/usr/bin/env python3
"""Build one ZIP containing public datasets missing from the user's Brazil MDR/RR-TB drive.

The bundle intentionally excludes sources already documented as present on the external drive:
SINAN TB 2016-2025, INMET 2016-2025, Census 2022 aggregates, municipal boundaries,
and REGIC 2018. It downloads the additional inputs most relevant to the V8 repair:

* official municipality -> health region / macroregion crosswalk;
* SINAN tuberculosis documentation;
* annual municipality population denominators;
* SISDEPEN prison-system data;
* historical CNES December snapshots (ST, SR and EQ) when available.

Every file is downloaded from an official public source, hashed, inventoried, and placed
in a single reproducible ZIP. Optional-source failures are recorded rather than hidden.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(os.environ.get("BUNDLE_WORKDIR", "bundle_work")).resolve()
RAW = ROOT / "BRAZIL_MDRTB_ADDITIONAL_PUBLIC_DATA"
CACHE = ROOT / "cache"
OUT_ZIP = ROOT / "BRAZIL_MDRTB_ADDITIONAL_PUBLIC_DATA.zip"

STATE_CODES = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]
YEARS = list(range(2016, 2026))


@dataclass
class ManifestRow:
    logical_dataset: str
    relative_path: str
    source_url: str
    source_organization: str
    retrieved_utc: str
    status: str
    bytes: int | None = None
    sha256: str | None = None
    notes: str | None = None


manifest: list[ManifestRow] = []
failures: list[dict[str, str]] = []


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": "Brazil-MDRTB-public-data-bundler/1.0 (+https://github.com/aidanshev/colon)",
        "Accept": "*/*",
    })
    return s


S = session()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dirs() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for p in [RAW, CACHE]:
        p.mkdir(parents=True, exist_ok=True)


def add_failure(dataset: str, url: str, exc: Exception | str) -> None:
    failures.append({
        "dataset": dataset,
        "url": url,
        "error": str(exc),
        "timestamp_utc": utc_now(),
    })
    print(f"[WARN] {dataset}: {exc}", file=sys.stderr)


def record_download(dataset: str, dest: Path, url: str, org: str, notes: str | None = None) -> None:
    manifest.append(ManifestRow(
        logical_dataset=dataset,
        relative_path=str(dest.relative_to(RAW)),
        source_url=url,
        source_organization=org,
        retrieved_utc=utc_now(),
        status="downloaded",
        bytes=dest.stat().st_size,
        sha256=sha256_file(dest),
        notes=notes,
    ))


def download(dataset: str, url: str, dest: Path, org: str, *, required: bool = False,
             min_bytes: int = 1, notes: str | None = None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with S.get(url, stream=True, timeout=(30, 180), allow_redirects=True) as r:
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        if tmp.stat().st_size < min_bytes:
            raise RuntimeError(f"downloaded file too small: {tmp.stat().st_size} bytes")
        # Reject obvious HTML login/error pages when binary/data expected.
        head = tmp.read_bytes()[:512].lstrip().lower()
        if (b"<html" in head or b"<!doctype html" in head) and dest.suffix.lower() not in {".html", ".htm"}:
            raise RuntimeError(f"received HTML instead of expected data ({ctype})")
        tmp.replace(dest)
        record_download(dataset, dest, r.url, org, notes)
        print(f"[OK] {dataset}: {dest} ({dest.stat().st_size:,} bytes)")
        return True
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        add_failure(dataset, url, exc)
        if required:
            raise
        return False


def download_health_region_crosswalk() -> None:
    url = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/dbgeral/macroregiao_de_saude_csv.zip"
    dest = RAW / "01_health_region_crosswalk" / "macroregiao_de_saude_csv.zip"
    download(
        "Official municipality-health-region-macroregion crosswalk",
        url,
        dest,
        "Brazil Ministry of Health / OpenDataSUS",
        required=True,
        min_bytes=1000,
        notes="Required to replace invalid municipality-code-prefix health-region assignments.",
    )
    # Verify archive and expose member listing.
    with zipfile.ZipFile(dest) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"health-region crosswalk ZIP failed integrity at {bad}")
        members = [{"name": i.filename, "bytes": i.file_size} for i in zf.infolist()]
    (dest.parent / "archive_members.json").write_text(json.dumps(members, indent=2), encoding="utf-8")


def download_sinan_docs() -> None:
    docs = {
        "Tuberculose_v5_notification_investigation_form.pdf":
            "https://portalsinan.saude.gov.br/images/documentos/Agravos/Tuberculose/Tuberculose_v5.pdf",
        "Instrutivo_Preenchimento_Tuberculose.pdf":
            "https://portalsinan.saude.gov.br/images/documentos/Agravos/Tuberculose/InstrutivodePreenchimento.pdf",
        "Dicionario_Dados_NET_Tuberculose_2020.pdf":
            "https://portalsinan.saude.gov.br/images/documentos/Agravos/Tuberculose/DICI_DADOS_NET_Tuberculose_23_07_2020.pdf",
        "Tuberculose_Ficha_Acompanhamento_v5.pdf":
            "https://portalsinan.saude.gov.br/images/documentos/Agravos/Tuberculose/Tuberculose_Acomp_v5.pdf",
        "Caderno_de_Analise_Tuberculose_2019.pdf":
            "https://portalsinan.saude.gov.br/images/documentos/Agravos/Tuberculose/Caderno_de_Analise_2019.pdf",
    }
    for name, url in docs.items():
        download(
            f"SINAN TB documentation: {name}",
            url,
            RAW / "02_sinan_documentation" / name,
            "Brazil Ministry of Health / SINAN",
            required=True,
            min_bytes=500,
        )


def sidra_to_dataframe(payload: list[dict]) -> pd.DataFrame:
    if not payload or len(payload) < 2:
        raise ValueError("SIDRA returned no data")
    header = payload[0]
    rows = payload[1:]
    # Each SIDRA data row already uses compact field keys. Header values describe them.
    df = pd.DataFrame(rows)
    df.attrs["header"] = header
    return df


def normalize_population_estimates(df: pd.DataFrame) -> pd.DataFrame:
    # Common SIDRA keys: D1C/D1N=period, D2C/D2N=territory, V=value.
    period_code = next((c for c in ["D1C", "D2C", "D3C"] if c in df.columns and df[c].astype(str).str.fullmatch(r"20\d{2}").mean() > 0.5), None)
    territory_code = next((c for c in ["D2C", "D3C", "D1C"] if c in df.columns and df[c].astype(str).str.fullmatch(r"\d{6,7}").mean() > 0.5), None)
    territory_name = territory_code[:-1] + "N" if territory_code else None
    if not period_code or not territory_code or territory_name not in df.columns or "V" not in df.columns:
        raise ValueError(f"Could not identify SIDRA population columns: {df.columns.tolist()}")
    out = pd.DataFrame({
        "municipality_code": df[territory_code].astype(str).str.extract(r"(\d{6,7})", expand=False),
        "municipality_name": df[territory_name].astype(str),
        "year": pd.to_numeric(df[period_code], errors="coerce").astype("Int64"),
        "population": pd.to_numeric(df["V"].astype(str).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False), errors="coerce").astype("Int64"),
    })
    out = out.dropna(subset=["municipality_code", "year", "population"]).drop_duplicates(["municipality_code", "year"])
    return out.sort_values(["year", "municipality_code"]).reset_index(drop=True)


def parse_ibge_aggregates_2022(payload: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for variable in payload:
        var_name = str(variable.get("variavel", ""))
        if "popula" not in var_name.lower():
            continue
        for result in variable.get("resultados", []):
            for series in result.get("series", []):
                locality = series.get("localidade", {})
                code = str(locality.get("id", ""))
                name = str(locality.get("nome", ""))
                values = series.get("serie", {})
                value = values.get("2022")
                if code and value not in (None, "", "..."):
                    rows.append({
                        "municipality_code": code,
                        "municipality_name": name,
                        "year": 2022,
                        "population": int(float(str(value).replace(",", "."))),
                    })
    if not rows:
        raise ValueError("IBGE aggregate API returned no 2022 municipal population rows")
    return pd.DataFrame(rows).drop_duplicates(["municipality_code", "year"]).sort_values("municipality_code")


def download_population() -> None:
    outdir = RAW / "03_population"
    outdir.mkdir(parents=True, exist_ok=True)

    estimate_url = (
        "https://apisidra.ibge.gov.br/values/t/6579/n6/all/v/9324/"
        "p/2016,2017,2018,2019,2020,2021,2023,2024,2025?formato=json"
    )
    census_url = (
        "https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos/2022/"
        "variaveis/93?localidades=N6[all]"
    )

    r1 = S.get(estimate_url, timeout=(30, 300))
    r1.raise_for_status()
    raw1 = outdir / "SIDRA_6579_population_estimates_2016_2025_excluding_2022.json"
    raw1.write_bytes(r1.content)
    record_download("IBGE SIDRA table 6579 raw JSON", raw1, r1.url, "IBGE")
    estimates = normalize_population_estimates(sidra_to_dataframe(r1.json()))

    try:
        r2 = S.get(census_url, timeout=(30, 300))
        r2.raise_for_status()
        raw2 = outdir / "IBGE_Census2022_table4714_population_raw.json"
        raw2.write_bytes(r2.content)
        record_download("IBGE Census 2022 population raw JSON", raw2, r2.url, "IBGE")
        census = parse_ibge_aggregates_2022(r2.json())
    except Exception as exc:
        add_failure("IBGE Census 2022 municipal population API", census_url, exc)
        # Secondary official SIDRA endpoint.
        fallback = "https://apisidra.ibge.gov.br/values/t/4714/n6/all/v/93/p/2022?formato=json"
        r2 = S.get(fallback, timeout=(30, 300))
        r2.raise_for_status()
        raw2 = outdir / "SIDRA_4714_Census2022_population_raw.json"
        raw2.write_bytes(r2.content)
        record_download("IBGE SIDRA table 4714 raw JSON", raw2, r2.url, "IBGE")
        census = normalize_population_estimates(sidra_to_dataframe(r2.json()))

    population = pd.concat([estimates, census], ignore_index=True).sort_values(["year", "municipality_code"])
    expected = set(range(2016, 2026))
    present = set(population["year"].astype(int).unique())
    if expected - present:
        raise RuntimeError(f"population years missing: {sorted(expected - present)}")
    csv_path = outdir / "municipality_population_2016_2025.csv"
    population.to_csv(csv_path, index=False)
    manifest.append(ManifestRow(
        logical_dataset="Normalized official IBGE municipality population 2016-2025",
        relative_path=str(csv_path.relative_to(RAW)),
        source_url=f"{estimate_url} ; {census_url}",
        source_organization="IBGE",
        retrieved_utc=utc_now(),
        status="generated_from_official_api",
        bytes=csv_path.stat().st_size,
        sha256=sha256_file(csv_path),
        notes=f"rows={len(population)}; municipalities={population.municipality_code.nunique()}",
    ))


def with_download_flag(url: str) -> list[str]:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    urls = [url]
    for key in ("download", "web"):
        q = query.copy()
        q[key] = "1"
        urls.append(urlunparse(parsed._replace(query=urlencode(q))))
    return list(dict.fromkeys(urls))


def download_sisdepen() -> None:
    page_url = "https://www.gov.br/senappen/pt-br/servicos/sisdepen/bases-de-dados"
    outdir = RAW / "04_sisdepen"
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        page = S.get(page_url, timeout=(30, 120))
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        anchors = soup.find_all("a", href=True)
        # Prefer the first CSV link after the Base Única heading.
        base_heading = soup.find(lambda tag: tag.name in {"h2", "h3", "h4"} and "base única" in tag.get_text(" ", strip=True).lower())
        candidates: list[str] = []
        if base_heading:
            for a in base_heading.find_all_next("a", href=True, limit=10):
                if "csv" in a.get_text(" ", strip=True).lower():
                    candidates.append(urljoin(page_url, a["href"]))
                    break
        if not candidates:
            for a in anchors:
                text = a.get_text(" ", strip=True).lower()
                href = urljoin(page_url, a["href"])
                if text == "csv" and ("sharepoint" in href or "download" in href):
                    candidates.append(href)
        candidates = list(dict.fromkeys(candidates))
        success = False
        for base in candidates:
            for url in with_download_flag(base):
                dest = outdir / "SISDEPEN_Base_Unica_all_cycles.csv"
                if download("SISDEPEN Base Única CSV", url, dest, "SENAPPEN", min_bytes=10_000):
                    success = True
                    break
            if success:
                break
        if not success:
            raise RuntimeError("Could not retrieve anonymous Base Única CSV from current official links")
    except Exception as exc:
        add_failure("SISDEPEN Base Única", page_url, exc)
        # Save current official page HTML so Codex can resolve any future link changes.
        try:
            html_path = outdir / "official_bases_de_dados_page.html"
            html_path.write_text(page.text, encoding="utf-8")
            record_download("SISDEPEN official download-page snapshot", html_path, page_url, "SENAPPEN", notes="Base data download failed; page preserved for reproducible link discovery.")
        except Exception:
            pass


def parse_directory_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.lower().endswith(".dbc"):
            links.append(href)
    return links


def download_cnes() -> None:
    base_urls = [
        "https://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Dados/",
        "http://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Dados/",
    ]
    outdir = RAW / "05_cnes_december_snapshots_2016_2025"
    outdir.mkdir(parents=True, exist_ok=True)
    links: list[str] = []
    used_base = None
    for base in base_urls:
        try:
            r = S.get(base, timeout=(30, 300))
            r.raise_for_status()
            links = parse_directory_links(r.text, base)
            if links:
                used_base = base
                break
        except Exception as exc:
            add_failure("CNES FTP/HTTP directory listing", base, exc)
    if not links:
        add_failure("CNES December snapshots", base_urls[0], "Could not enumerate official directory")
        return

    selected: list[tuple[str, str, int, int, str]] = []
    pattern = re.compile(r"/(ST|SR|EQ)([A-Z]{2})(\d{2})(\d{2})\.dbc$", re.I)
    for url in links:
        m = pattern.search(url)
        if not m:
            continue
        group, state, yy, mm = m.groups()
        year = 2000 + int(yy)
        month = int(mm)
        if group.upper() in {"ST", "SR", "EQ"} and state.upper() in STATE_CODES and year in YEARS and month == 12:
            selected.append((group.upper(), state.upper(), year, month, url))

    # Expected maximum is 810 files; tolerate files absent from historical catalog but record coverage.
    coverage_rows = []
    for group in ["ST", "SR", "EQ"]:
        for year in YEARS:
            for state in STATE_CODES:
                match = next((x for x in selected if x[0] == group and x[1] == state and x[2] == year), None)
                if not match:
                    coverage_rows.append({"group": group, "state": state, "year": year, "month": 12, "status": "not_listed"})
                    continue
                _, _, _, _, url = match
                dest = outdir / group / str(year) / Path(urlparse(url).path).name.upper()
                ok = download(
                    f"CNES {group} December snapshot {state} {year}",
                    url,
                    dest,
                    "Brazil Ministry of Health / DATASUS CNES",
                    min_bytes=100,
                    notes=f"Official CNES {group} December snapshot; state={state}; year={year}",
                )
                coverage_rows.append({"group": group, "state": state, "year": year, "month": 12, "status": "downloaded" if ok else "failed"})

    with (outdir / "coverage.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["group", "state", "year", "month", "status"])
        writer.writeheader()
        writer.writerows(coverage_rows)


def download_cnes_docs() -> None:
    page_url = "https://cnes.datasus.gov.br/pages/downloads/documentacao.jsp"
    outdir = RAW / "06_cnes_documentation"
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        r = S.get(page_url, timeout=(30, 120))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(page_url, a["href"])
            text = a.get_text(" ", strip=True)
            if any(ext in href.lower() for ext in [".pdf", ".zip", ".xls", ".xlsx", ".csv"]):
                links.append((text, href))
        for idx, (text, url) in enumerate(dict.fromkeys(links), start=1):
            name = Path(urlparse(url).path).name or f"cnes_document_{idx}"
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
            download(f"CNES documentation: {text or safe}", url, outdir / safe, "DATASUS CNES")
        page_path = outdir / "documentation_page.html"
        page_path.write_text(r.text, encoding="utf-8")
        record_download("CNES documentation-page snapshot", page_path, page_url, "DATASUS CNES")
    except Exception as exc:
        add_failure("CNES documentation", page_url, exc)


def write_metadata() -> None:
    # Manifest
    manifest_path = RAW / "MANIFEST.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(asdict(ManifestRow("", "", "", "", "", "")).keys())
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest:
            writer.writerow(asdict(row))

    (RAW / "MANIFEST.json").write_text(
        json.dumps([asdict(x) for x in manifest], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (RAW / "DOWNLOAD_FAILURES.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    checksums = []
    for p in sorted(RAW.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            checksums.append(f"{sha256_file(p)}  {p.relative_to(RAW)}")
    (RAW / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    readme = f"""# Brazil MDR/RR-TB additional public-data bundle

Generated: {utc_now()}

This ZIP contains additional public inputs that were not documented as present on the user's external drive after the V7 audit:

1. Official municipality-to-health-region/macroregion crosswalk.
2. Official SINAN tuberculosis form, instructions, data dictionary, follow-up form, and analysis guide.
3. Official IBGE municipality population denominators for 2016-2025, including 2022 Census population.
4. SISDEPEN public prison-system data when the official anonymous link was accessible.
5. CNES December ST/SR/EQ snapshots for 2016-2025 when listed and accessible through the official DATASUS directory.
6. CNES documentation discovered from the official page.

Already-present sources intentionally excluded: SINAN TB 2016-2025, INMET 2016-2025, Census 2022 aggregates, BR_Municipios_2024 boundaries, and REGIC 2018.

`MANIFEST.csv` and `SHA256SUMS.txt` provide provenance and integrity. `DOWNLOAD_FAILURES.json` records any source that the official host did not permit the GitHub runner to retrieve.

Copy or extract this directory into the external-drive `brazil` folder. Codex should classify by manifest and must not assume optional failures were downloaded.
"""
    (RAW / "README.md").write_text(readme, encoding="utf-8")


def build_zip() -> None:
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for p in sorted(RAW.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(Path(RAW.name) / p.relative_to(RAW)))
    with zipfile.ZipFile(OUT_ZIP) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"final ZIP failed at {bad}")
    print(f"FINAL_ZIP={OUT_ZIP}")
    print(f"FINAL_ZIP_BYTES={OUT_ZIP.stat().st_size}")
    print(f"FINAL_ZIP_SHA256={sha256_file(OUT_ZIP)}")
    print(f"MANIFEST_FILES={len(manifest)}")
    print(f"DOWNLOAD_FAILURES={len(failures)}")


def main() -> None:
    ensure_dirs()
    download_health_region_crosswalk()
    download_sinan_docs()
    download_population()
    download_sisdepen()
    download_cnes()
    download_cnes_docs()
    write_metadata()
    build_zip()


if __name__ == "__main__":
    main()
