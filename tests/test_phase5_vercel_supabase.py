"""
Phase 5 Vercel + Supabase Cloud-Readiness Verification Tests:
  - Vercel ASGI entrypoint & vercel.json validation
  - Supabase Storage REST backend contract (mocked HTTP)
  - Supabase RLS & private bucket migration SQL audit
  - Clean production seed verification (ZERO synthetic users/data)
  - Serverless PPTX generation latency benchmark (< 5s vs 60s Vercel Pro limit)
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import BASE_DIR
from app.engine.mapping import MappingRegistry
from app.engine.ooxml_editor import PowerPointEngine
from app.storage import LocalStorageBackend, SupabaseStorageBackend

TEMPLATE_PPTX = Path(__import__("os").environ.get("TOMOH_TEMPLATE_PPTX", "/vercel/master_template.pptx"))


class TomohPhase5VercelSupabaseTests(unittest.TestCase):
    def test_01_vercel_entrypoint_and_config_valid(self) -> None:
        cfg = json.loads((BASE_DIR / "vercel.json").read_text(encoding="utf-8"))
        self.assertNotIn("builds", cfg)
        self.assertEqual(cfg["functions"]["api/index.py"]["maxDuration"], 60)
        self.assertEqual(cfg["rewrites"][0]["destination"], "/api/index.py")
        # Verify ASGI entrypoint imports cleanly
        import api.index as vercel_entry
        self.assertTrue(hasattr(vercel_entry, "app"))

    def test_02_supabase_rls_and_clean_prod_seed(self) -> None:
        rls_sql = (BASE_DIR / "migrations" / "004_supabase_rls_and_storage.sql").read_text(encoding="utf-8")
        for tbl in ("users", "projects", "reporting_weeks", "weekly_submissions", "kpi_values", "report_generations", "audit_history"):
            self.assertIn(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;", rls_sql)
        for bkt in ("tomoh-templates", "tomoh-reports", "tomoh-uploads", "tomoh-attachments"):
            self.assertIn(f"'{bkt}'", rls_sql)
        self.assertIn("false", rls_sql)  # All buckets private

        prod_seed = (BASE_DIR / "migrations" / "002_seed_tomoh_master_prod.sql").read_text(encoding="utf-8")
        self.assertNotIn("INSERT INTO users", prod_seed)
        self.assertNotIn("coordinator@tomoh.internal", prod_seed)

    def test_03_supabase_storage_backend_contract(self) -> None:
        sb = SupabaseStorageBackend("https://example.supabase.co", "test-service-key")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"signedURL": "/object/sign/tomoh-reports/w45.pptx?token=abc"}).encode()
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as m_open:
            uri = sb.upload_bytes("tomoh-reports", "w45.pptx", b"PK\x03\x04", "application/octet-stream")
            self.assertEqual(uri, "supabase://tomoh-reports/w45.pptx")
            signed = sb.create_signed_url("tomoh-reports", "w45.pptx", 300)
            self.assertIn("https://example.supabase.co/storage/v1/object/sign/tomoh-reports/w45.pptx", signed)
            self.assertEqual(m_open.call_count, 2)

    def test_04_serverless_pptx_generation_latency_benchmark(self) -> None:
        reg = MappingRegistry(BASE_DIR / "config" / "mapping_config.json")
        eng = PowerPointEngine(reg)
        with tempfile.TemporaryDirectory() as tmp:
            out_p = Path(tmp) / "bench.pptx"
            t0 = time.perf_counter()
            res = eng.generate(
                template_pptx=TEMPLATE_PPTX,
                field_values={"metadata.report_title_ar": "التقرير الأسبوعي رقم (45)", "kpi.SMI_WEEKLY": 12},
                output_pptx=out_p,
            )
            elapsed = time.perf_counter() - t0
            self.assertEqual(res.operations_failed, 0)
            # Must stay comfortably under Vercel's 10s Hobby / 60s Pro serverless execution limit
            self.assertLess(elapsed, 5.0, f"PPTX generation too slow for serverless: {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
