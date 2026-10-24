"""Zip Export Service.

Handles standalone extraction and compression of workflow files when
the Project Manager is not available.
"""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.workflow import WorkflowContext

logger = get_logger(__name__, "flow_cytometry")


class ZipExportService:
    """Handles saving and loading workflows as standalone .zip archives."""

    @staticmethod
    def save_standalone(workflow_service: Any, path: str) -> None:
        """Export workflow to a standalone zip file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            context = WorkflowContext(resolve_base=tmp_path)

            # 1. Get the payload and generate attachments via service
            payload = workflow_service.export_workflow(context=context)

            # 2. Serialize attachments array into payload
            payload["_attachments"] = []

            # 3. Copy all pending attachments to temp dir
            for key, att_info in context.pending_attachments.items():
                src = att_info["source_path"]
                dst = tmp_path / src.name
                shutil.copy2(src, dst)
                payload["_attachments"].append(
                    {
                        "key": key,
                        "filename": src.name,
                        "relative_path": src.name,
                        "mime_hint": att_info.get("mime_hint", "application/octet-stream"),
                        "description": att_info.get("description", ""),
                    }
                )

            # 4. Write workflow.json
            with open(tmp_path / "workflow.json", "w") as f:
                json.dump(payload, f, indent=2)

            # 5. Zip it all into the destination file
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in tmp_path.iterdir():
                    zf.write(item, arcname=item.name)
