"""
Production Surgical OOXML PowerPoint Generation Engine for TOMOH Weekly Reports.

Capabilities:
  - Byte-for-byte preservation of all untouched slides, masters, layouts, themes,
    charts, OLE objects, media, notes, tags, and webextensions.
  - Surgical Arabic RTL text replacement preserving <a:pPr> and <a:rPr> (29LT Azer).
  - Project status badge updates mapping all 6 official statuses to Monsha'at RGB hex fills.
  - Native table cell editing + safe dynamic row add/remove on resizable tables
    (with explicit flagging for non-resizable tables).
  - Aspect-ratio-preserving image replacement into designated <p:pic> slots using
    isolated media parts (never mutating shared media on other slides).
  - Deterministic ZIP output timestamps for reproducible builds.
"""

from __future__ import annotations

import copy
import hashlib
import io
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree
from PIL import Image, ImageOps

from app.engine.mapping import FieldMapping, MappingRegistry

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
A_NS = f"{{{NS['a']}}}"
P_NS = f"{{{NS['p']}}}"
R_NS = f"{{{NS['r']}}}"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


@dataclass
class EngineOperationLog:
    slide_number: int
    field_key: str
    object_type: str
    object_id: str
    status: str  # "updated" | "skipped_missing" | "error"
    old_preview: str = ""
    new_preview: str = ""
    warning: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EngineResult:
    template_path: str
    template_sha256: str
    output_path: str
    output_sha256: str
    slides_modified: List[int] = field(default_factory=list)
    slides_untouched: int = 0
    operations_updated: int = 0
    operations_skipped_missing: int = 0
    operations_failed: int = 0
    warnings: List[str] = field(default_factory=list)
    operations: List[EngineOperationLog] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_txbody_text(tx_body: Optional[etree._Element]) -> str:
    if tx_body is None:
        return ""
    lines = []
    for p in tx_body.findall("a:p", NS):
        lines.append("".join(t.text or "" for t in p.findall("a:r/a:t", NS)))
    return "\n".join(lines).strip()


def _surgical_replace_txbody(
    tx_body: etree._Element,
    new_text: str,
    fallback_rpr: Optional[etree._Element] = None,
    fallback_ppr: Optional[etree._Element] = None,
    override_text_hex: Optional[str] = None,
) -> None:
    existing_ps = tx_body.findall("a:p", NS)
    template_p = existing_ps[0] if existing_ps else None

    template_ppr = None
    template_rpr = None
    if template_p is not None:
        ppr = template_p.find("a:pPr", NS)
        if ppr is not None:
            template_ppr = copy.deepcopy(ppr)
        first_r = template_p.find("a:r", NS)
        if first_r is not None and first_r.find("a:rPr", NS) is not None:
            template_rpr = copy.deepcopy(first_r.find("a:rPr", NS))
        elif template_p.find("a:endParaRPr", NS) is not None:
            epr = template_p.find("a:endParaRPr", NS)
            template_rpr = etree.Element(f"{A_NS}rPr", **epr.attrib)
            for child in epr:
                template_rpr.append(copy.deepcopy(child))

    if template_rpr is None and fallback_rpr is not None:
        template_rpr = copy.deepcopy(fallback_rpr)
    if template_ppr is None and fallback_ppr is not None:
        template_ppr = copy.deepcopy(fallback_ppr)

    if override_text_hex and template_rpr is not None:
        for old_fill in list(template_rpr.findall("a:solidFill", NS)):
            template_rpr.remove(old_fill)
        sf = etree.Element(f"{A_NS}solidFill")
        etree.SubElement(sf, f"{A_NS}srgbClr", val=override_text_hex)
        template_rpr.insert(0, sf)

    lines = new_text.split("\n")
    for p in existing_ps:
        tx_body.remove(p)

    for idx, line in enumerate(lines):
        new_p = etree.SubElement(tx_body, f"{A_NS}p")
        if idx < len(existing_ps) and existing_ps[idx].find("a:pPr", NS) is not None:
            new_p.append(copy.deepcopy(existing_ps[idx].find("a:pPr", NS)))
        elif template_ppr is not None:
            new_p.append(copy.deepcopy(template_ppr))

        if line != "":
            new_r = etree.SubElement(new_p, f"{A_NS}r")
            if template_rpr is not None:
                new_r.append(copy.deepcopy(template_rpr))
            new_t = etree.SubElement(new_r, f"{A_NS}t")
            new_t.text = line

        if template_rpr is not None:
            end_rpr = etree.SubElement(new_p, f"{A_NS}endParaRPr", **template_rpr.attrib)
            for child in template_rpr:
                end_rpr.append(copy.deepcopy(child))


def _set_tc_solid_fill(tc: etree._Element, fill_hex: str) -> None:
    tc_pr = tc.find("a:tcPr", NS)
    if tc_pr is None:
        tc_pr = etree.SubElement(tc, f"{A_NS}tcPr")
    for tag in ("a:solidFill", "a:noFill", "a:gradFill"):
        for existing in list(tc_pr.findall(tag, NS)):
            tc_pr.remove(existing)
    sf = etree.SubElement(tc_pr, f"{A_NS}solidFill")
    etree.SubElement(sf, f"{A_NS}srgbClr", val=fill_hex)


def _find_shape(slide_root: etree._Element, shape_id: str) -> Optional[etree._Element]:
    matches = slide_root.xpath(f'.//p:sp[p:nvSpPr/p:cNvPr[@id="{shape_id}"]]', namespaces=NS)
    return matches[0] if matches else None


def _find_table(slide_root: etree._Element, table_id: str) -> Optional[etree._Element]:
    matches = slide_root.xpath(
        f'.//p:graphicFrame[p:nvGraphicFramePr/p:cNvPr[@id="{table_id}"]]//a:tbl',
        namespaces=NS,
    )
    return matches[0] if matches else None


def _find_pic(slide_root: etree._Element, pic_id: str) -> Optional[etree._Element]:
    matches = slide_root.xpath(f'.//p:pic[p:nvPicPr/p:cNvPr[@id="{pic_id}"]]', namespaces=NS)
    return matches[0] if matches else None


def _find_col_fallback_style(tbl: etree._Element, col_idx: int) -> Tuple[Optional[etree._Element], Optional[etree._Element]]:
    rows = tbl.findall("a:tr", NS)
    for r in rows[1:]:
        cells = r.findall("a:tc", NS)
        if col_idx < len(cells):
            tx = cells[col_idx].find("a:txBody", NS)
            if tx is not None:
                rpr = tx.find(".//a:r/a:rPr", NS)
                ppr = tx.find(".//a:p/a:pPr", NS)
                if rpr is not None:
                    return rpr, ppr
    return None, None


def _prepare_aspect_cropped_png(image_path: Path, box_cx_emu: int, box_cy_emu: int) -> bytes:
    """Center-crop image to match target PowerPoint slot aspect ratio without distortion."""
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        if box_cx_emu > 0 and box_cy_emu > 0:
            target_aspect = box_cx_emu / float(box_cy_emu)
            target_w = min(max(img_rgb.width, 600), 1600)
            target_h = max(1, int(round(target_w / target_aspect)))
            cropped = ImageOps.fit(img_rgb, (target_w, target_h), method=Image.Resampling.LANCZOS)
        else:
            cropped = img_rgb
        buf = io.BytesIO()
        cropped.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


class PowerPointEngine:
    def __init__(self, registry: MappingRegistry):
        self.registry = registry

    def generate(
        self,
        *,
        template_pptx: Path,
        field_values: Dict[str, Any],
        output_pptx: Path,
    ) -> EngineResult:
        template_pptx = Path(template_pptx).resolve()
        output_pptx = Path(output_pptx).resolve()
        if template_pptx == output_pptx:
            raise ValueError("Refusing to overwrite the immutable original template PPTX.")

        template_sha = _sha256_file(template_pptx)
        output_pptx.parent.mkdir(parents=True, exist_ok=True)

        # Group mappings by slide number
        by_slide: Dict[int, List[FieldMapping]] = {}
        for m in self.registry.mappings:
            by_slide.setdefault(m.slide_number, []).append(m)

        ops_log: List[EngineOperationLog] = []
        warnings: List[str] = []
        modified_slides: set[int] = set()
        injected_media: Dict[str, bytes] = {}
        modified_rels: Dict[str, bytes] = {}

        with zipfile.ZipFile(template_pptx, "r") as zin:
            total_slides = sum(
                1 for n in zin.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            slide_xml_overrides: Dict[str, bytes] = {}

            for sn, mappings in sorted(by_slide.items()):
                slide_entry = f"ppt/slides/slide{sn}.xml"
                if slide_entry not in zin.namelist():
                    for m in mappings:
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="error",
                                error=f"Slide entry {slide_entry} missing from template",
                            )
                        )
                    continue

                parser = etree.XMLParser(remove_blank_text=False)
                slide_root = etree.fromstring(zin.read(slide_entry), parser=parser)
                slide_dirty = False

                for m in mappings:
                    raw_val = field_values.get(m.field_key)
                    formatted, err = self.registry.format_value(m, raw_val)
                    if err:
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="error",
                                error=err,
                            )
                        )
                        continue
                    if formatted is None:
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="skipped_missing",
                            )
                        )
                        continue

                    if m.object_type == "shape":
                        sp = _find_shape(slide_root, m.object_id)
                        if sp is None:
                            ops_log.append(
                                EngineOperationLog(
                                    slide_number=sn,
                                    field_key=m.field_key,
                                    object_type=m.object_type,
                                    object_id=m.object_id,
                                    status="error",
                                    error=f"Shape id={m.object_id} not found on slide {sn}",
                                )
                            )
                            continue
                        tx = sp.find("p:txBody", NS)
                        old_txt = _extract_txbody_text(tx)
                        warn = None
                        max_c = m.validation.get("max_chars")
                        if max_c and len(str(formatted)) > max_c:
                            warn = f"Slide {sn} ({m.field_key}): length {len(str(formatted))} exceeds max_chars={max_c}"
                            warnings.append(warn)
                        _surgical_replace_txbody(tx, str(formatted))
                        slide_dirty = True
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="updated",
                                old_preview=old_txt[:60],
                                new_preview=str(formatted)[:60],
                                warning=warn,
                            )
                        )

                    elif m.object_type in ("table_cell", "status_table_cell"):
                        tbl = _find_table(slide_root, m.object_id)
                        if tbl is None or m.row is None or m.col is None:
                            ops_log.append(
                                EngineOperationLog(
                                    slide_number=sn,
                                    field_key=m.field_key,
                                    object_type=m.object_type,
                                    object_id=m.object_id,
                                    status="error",
                                    error=f"Table id={m.object_id} or coordinates missing on slide {sn}",
                                )
                            )
                            continue
                        rows = tbl.findall("a:tr", NS)
                        if m.row >= len(rows) or m.col >= len(rows[m.row].findall("a:tc", NS)):
                            ops_log.append(
                                EngineOperationLog(
                                    slide_number=sn,
                                    field_key=m.field_key,
                                    object_type=m.object_type,
                                    object_id=m.object_id,
                                    status="error",
                                    error=f"Cell [{m.row},{m.col}] out of bounds on slide {sn}",
                                )
                            )
                            continue
                        tc = rows[m.row].findall("a:tc", NS)[m.col]
                        tx = tc.find("a:txBody", NS)
                        old_txt = _extract_txbody_text(tx)
                        fb_rpr, fb_ppr = _find_col_fallback_style(tbl, m.col)
                        if m.object_type == "status_table_cell":
                            style_dict = formatted  # {"label_ar", "fill_hex", "text_hex"}
                            _set_tc_solid_fill(tc, style_dict["fill_hex"])
                            _surgical_replace_txbody(
                                tx,
                                style_dict["label_ar"],
                                fallback_rpr=fb_rpr,
                                fallback_ppr=fb_ppr,
                                override_text_hex=style_dict["text_hex"],
                            )
                            new_prev = f"{style_dict['label_ar']} (#{style_dict['fill_hex']})"
                        else:
                            _surgical_replace_txbody(tx, str(formatted), fallback_rpr=fb_rpr, fallback_ppr=fb_ppr)
                            new_prev = str(formatted)[:60]
                        slide_dirty = True
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=f"{m.object_id}[{m.row},{m.col}]",
                                status="updated",
                                old_preview=old_txt[:60],
                                new_preview=new_prev,
                            )
                        )

                    elif m.object_type == "table_rows":
                        tbl = _find_table(slide_root, m.object_id)
                        if tbl is None or not m.columns:
                            ops_log.append(
                                EngineOperationLog(
                                    slide_number=sn,
                                    field_key=m.field_key,
                                    object_type=m.object_type,
                                    object_id=m.object_id,
                                    status="error",
                                    error=f"Table id={m.object_id} or columns missing on slide {sn}",
                                )
                            )
                            continue
                        tr_list = tbl.findall("a:tr", NS)
                        data_rows = tr_list[1:]  # Row 0 is header
                        incoming_rows: List[Dict[str, Any]] = formatted
                        max_rows = int(m.validation.get("max_rows", len(data_rows)))
                        warn = None
                        if len(incoming_rows) > max_rows:
                            warn = (
                                f"Slide {sn} ({m.field_key}): {len(incoming_rows)} rows exceeds safe "
                                f"max_rows={max_rows}; truncated to {max_rows} to prevent slide overflow"
                            )
                            warnings.append(warn)
                            incoming_rows = incoming_rows[:max_rows]

                        if not m.resizable and len(incoming_rows) != len(data_rows):
                            warn = f"Slide {sn} ({m.field_key}): table marked non-resizable; row count capped at {len(data_rows)}"
                            warnings.append(warn)
                            incoming_rows = incoming_rows[: len(data_rows)]

                        # Safely add or remove data rows by cloning/removing <a:tr>
                        if m.resizable:
                            while len(data_rows) < len(incoming_rows):
                                cloned = copy.deepcopy(data_rows[-1])
                                tbl.append(cloned)
                                data_rows.append(cloned)
                            while len(data_rows) > len(incoming_rows) and len(data_rows) > 1:
                                to_rm = data_rows.pop()
                                tbl.remove(to_rm)

                        col_fallbacks = [_find_col_fallback_style(tbl, ci) for ci in range(len(m.columns))]
                        for ri, row_dict in enumerate(incoming_rows):
                            cells = data_rows[ri].findall("a:tc", NS)
                            for ci, col_key in enumerate(m.columns):
                                if ci < len(cells):
                                    tx = cells[ci].find("a:txBody", NS)
                                    val_str = str(row_dict.get(col_key, ""))
                                    fb_rpr, fb_ppr = col_fallbacks[ci]
                                    _surgical_replace_txbody(tx, val_str, fallback_rpr=fb_rpr, fallback_ppr=fb_ppr)
                        slide_dirty = True
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="updated",
                                old_preview=f"{len(tr_list)-1} rows",
                                new_preview=f"{len(incoming_rows)} rows",
                                warning=warn,
                            )
                        )

                    elif m.object_type == "image_replace":
                        img_path = Path(str(formatted))
                        pic = _find_pic(slide_root, m.object_id)
                        if pic is None or not img_path.exists():
                            ops_log.append(
                                EngineOperationLog(
                                    slide_number=sn,
                                    field_key=m.field_key,
                                    object_type=m.object_type,
                                    object_id=m.object_id,
                                    status="error",
                                    error=f"Picture id={m.object_id} or image '{img_path}' not found",
                                )
                            )
                            continue
                        ext = pic.find("p:spPr/a:xfrm/a:ext", NS)
                        cx, cy = (int(ext.get("cx", 0)), int(ext.get("cy", 0))) if ext is not None else (0, 0)
                        png_bytes = _prepare_aspect_cropped_png(img_path, cx, cy)
                        media_name = f"tomoh_injected_s{sn}_p{m.object_id}.png"
                        media_zip_path = f"ppt/media/{media_name}"
                        injected_media[media_zip_path] = png_bytes

                        # Update slide rels with a new unique rId
                        rels_entry = f"ppt/slides/_rels/slide{sn}.xml.rels"
                        rels_bytes = modified_rels.get(rels_entry, zin.read(rels_entry))
                        rels_root = etree.fromstring(rels_bytes)
                        existing_rids = {r.get("Id") for r in rels_root}
                        new_idx = 100
                        while f"rId{new_idx}" in existing_rids:
                            new_idx += 1
                        new_rid = f"rId{new_idx}"
                        etree.SubElement(
                            rels_root,
                            f"{{{NS['rel']}}}Relationship",
                            Id=new_rid,
                            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                            Target=f"../media/{media_name}",
                        )
                        modified_rels[rels_entry] = etree.tostring(
                            rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
                        )

                        # Update <a:blip r:embed="..."> and clear stale svgBlip extLst
                        blip = pic.find(".//a:blip", NS)
                        if blip is not None:
                            blip.set(f"{R_NS}embed", new_rid)
                            for ext_lst in list(blip.findall("a:extLst", NS)):
                                blip.remove(ext_lst)
                        slide_dirty = True
                        ops_log.append(
                            EngineOperationLog(
                                slide_number=sn,
                                field_key=m.field_key,
                                object_type=m.object_type,
                                object_id=m.object_id,
                                status="updated",
                                old_preview="template_graphic",
                                new_preview=media_name,
                            )
                        )

                if slide_dirty:
                    modified_slides.add(sn)
                    slide_xml_overrides[slide_entry] = etree.tostring(
                        slide_root, xml_declaration=True, encoding="UTF-8", standalone=True
                    )

            # Write output ZIP cleanly with deterministic metadata
            with zipfile.ZipFile(output_pptx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.filename in slide_xml_overrides:
                        zi = zipfile.ZipInfo(item.filename, date_time=FIXED_ZIP_TIME)
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zout.writestr(zi, slide_xml_overrides[item.filename])
                    elif item.filename in modified_rels:
                        zi = zipfile.ZipInfo(item.filename, date_time=FIXED_ZIP_TIME)
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zout.writestr(zi, modified_rels[item.filename])
                    else:
                        zout.writestr(item, zin.read(item.filename))

                for mpath, mbytes in sorted(injected_media.items()):
                    zi = zipfile.ZipInfo(mpath, date_time=FIXED_ZIP_TIME)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(zi, mbytes)

        output_sha = _sha256_file(output_pptx)
        return EngineResult(
            template_path=str(template_pptx),
            template_sha256=template_sha,
            output_path=str(output_pptx),
            output_sha256=output_sha,
            slides_modified=sorted(modified_slides),
            slides_untouched=total_slides - len(modified_slides),
            operations_updated=sum(1 for o in ops_log if o.status == "updated"),
            operations_skipped_missing=sum(1 for o in ops_log if o.status == "skipped_missing"),
            operations_failed=sum(1 for o in ops_log if o.status == "error"),
            warnings=warnings,
            operations=ops_log,
        )
