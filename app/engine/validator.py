"""Structural OOXML validator and optional LibreOffice visual comparison validator."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def validate_structure(
    *,
    original_pptx: Path,
    generated_pptx: Path,
    expected_modified_slides: List[int],
) -> Dict[str, Any]:
    """Verify slide count, dimensions, layouts, shape preservation, ZIP integrity, and RTL."""
    prs_o = Presentation(str(original_pptx))
    prs_g = Presentation(str(generated_pptx))

    slide_count_match = len(prs_o.slides) == len(prs_g.slides)
    dimensions_match = (prs_o.slide_width, prs_o.slide_height) == (
        prs_g.slide_width,
        prs_g.slide_height,
    )
    layout_mismatches = [
        i + 1
        for i, (so, sg) in enumerate(zip(prs_o.slides, prs_g.slides))
        if so.slide_layout.name != sg.slide_layout.name
    ]
    shape_count_mismatches = [
        i + 1
        for i, (so, sg) in enumerate(zip(prs_o.slides, prs_g.slides))
        if len(so.shapes) != len(sg.shapes)
    ]

    with zipfile.ZipFile(original_pptx, "r") as zo, zipfile.ZipFile(generated_pptx, "r") as zg:
        names_o = set(zo.namelist())
        names_g = set(zg.namelist())
        added_parts = sorted(names_g - names_o)
        removed_parts = sorted(names_o - names_g)
        modified_parts = []
        identical_parts = 0
        for name in sorted(names_o & names_g):
            if hashlib.sha256(zo.read(name)).digest() != hashlib.sha256(zg.read(name)).digest():
                modified_parts.append(name)
            else:
                identical_parts += 1

        # Verify RTL paragraphs still present on modified slides
        rtl_preserved = True
        for sn in expected_modified_slides:
            s_entry = f"ppt/slides/slide{sn}.xml"
            if s_entry in names_g:
                root_o = etree.fromstring(zo.read(s_entry))
                root_g = etree.fromstring(zg.read(s_entry))
                rtl_o = len(root_o.xpath('.//a:pPr[@rtl="1"]', namespaces=NS))
                rtl_g = len(root_g.xpath('.//a:pPr[@rtl="1"]', namespaces=NS))
                if rtl_o > 0 and rtl_g == 0:
                    rtl_preserved = False

    passed = (
        slide_count_match
        and dimensions_match
        and len(layout_mismatches) == 0
        and len(shape_count_mismatches) == 0
        and len(removed_parts) == 0
        and rtl_preserved
    )
    return {
        "passed": passed,
        "slide_count": len(prs_g.slides),
        "slide_count_match": slide_count_match,
        "dimensions_match": dimensions_match,
        "layout_mismatches": layout_mismatches,
        "shape_count_mismatches": shape_count_mismatches,
        "rtl_preserved": rtl_preserved,
        "zip_identical_parts": identical_parts,
        "zip_modified_parts": modified_parts,
        "zip_added_parts": added_parts,
        "zip_removed_parts": removed_parts,
    }


def run_visual_comparison(
    *,
    original_pptx: Path,
    generated_pptx: Path,
    slides_to_compare: List[int],
    output_dir: Path,
) -> Dict[str, Any]:
    """Render selected slides via LibreOffice + pdftoppm and build side-by-side PNG diffs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {"engine": "libreoffice_impress", "slides": {}, "comparison_images": []}

    with tempfile.TemporaryDirectory(prefix="tomoh_vis_") as tmp:
        tmp_path = Path(tmp)
        env = {**os.environ, "HOME": "/tmp", "TMPDIR": "/tmp"}

        def _to_pdf(src: Path, tag: str) -> Path:
            out_sub = tmp_path / tag
            out_sub.mkdir(parents=True, exist_ok=True)
            lo_prof = tmp_path / f"prof_{tag}"
            subprocess.run(
                [
                    "libreoffice",
                    f"-env:UserInstallation=file://{lo_prof}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_sub),
                    str(src),
                ],
                env=env,
                check=True,
                timeout=45,
                capture_output=True,
            )
            pdfs = list(out_sub.glob("*.pdf"))
            if not pdfs:
                raise RuntimeError(f"LibreOffice produced no PDF for {src}")
            return pdfs[0]

        pdf_o = _to_pdf(original_pptx, "orig")
        pdf_g = _to_pdf(generated_pptx, "gen")

        for sn in slides_to_compare:
            o_pref = tmp_path / f"o_{sn}"
            g_pref = tmp_path / f"g_{sn}"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "120", "-f", str(sn), "-l", str(sn), str(pdf_o), str(o_pref)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["pdftoppm", "-png", "-r", "120", "-f", str(sn), "-l", str(sn), str(pdf_g), str(g_pref)],
                check=True,
                capture_output=True,
            )
            img_o_path = sorted(tmp_path.glob(f"o_{sn}-*.png"))[0]
            img_g_path = sorted(tmp_path.glob(f"g_{sn}-*.png"))[0]

            im_o = Image.open(img_o_path).convert("RGB")
            im_g = Image.open(img_g_path).convert("RGB")
            diff = np.abs(np.array(im_o, dtype=np.int16) - np.array(im_g, dtype=np.int16))
            pct_diff = round(float(np.mean(diff.max(axis=2) > 5) * 100.0), 3)

            w, h = im_o.size
            header_h = 40
            canvas = Image.new("RGB", (w * 2 + 16, h + header_h), (245, 247, 250))
            draw = ImageDraw.Draw(canvas)
            draw.text((16, 12), f"ORIGINAL Template - Slide {sn}", fill=(15, 23, 42))
            draw.text((w + 32, 12), f"GENERATED Phase 1 - Slide {sn} (diff={pct_diff}%)", fill=(0, 102, 128))
            canvas.paste(im_o, (0, header_h))
            canvas.paste(im_g, (w + 16, header_h))
            cmp_path = output_dir / f"compare_slide_{sn:02d}.png"
            canvas.save(cmp_path)

            results["slides"][str(sn)] = {"pixel_diff_pct": pct_diff, "comparison_png": str(cmp_path)}
            results["comparison_images"].append(str(cmp_path))

    return results
