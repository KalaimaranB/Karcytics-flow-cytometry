"""Workspace Save Service.

Handles interactions with the central ProjectManager for saving and
loading workflows.
"""

from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.workflow import WorkflowContext

logger = get_logger(__name__, "flow_cytometry")


class WorkspaceSaveService:
    """Delegates persistence to the Karcytics SDK ProjectManager."""

    @staticmethod
    def save_to_pm(
        pm: Any,
        workflow_service: Any,
        filename: str | None,
        metadata: dict[str, Any],
        module_id: str,
    ) -> str:
        """Save a new (`filename` None) or existing workflow to the ProjectManager."""
        context = WorkflowContext()
        payload = workflow_service.export_workflow(context=context, project_dir=pm.project_dir)

        # 1. Save initially to establish the workflow file and get the generated filename
        new_filename = pm.save_workflow(
            module_id=module_id,
            payload=payload,
            metadata=metadata,
            filename=filename,
            attachments=[],
        )

        # 2. Process attachments now that we have a filename
        attachments = pm.workflows.load_attachments(new_filename) or []
        existing_keys = {a.get("key") for a in attachments}

        for key, att_info in context.pending_attachments.items():
            if "source_path" in att_info:
                try:
                    att_record = pm.attach_workflow_file(
                        wf_filename=new_filename,
                        source_path=att_info["source_path"],
                        key=key,
                        description=att_info.get("description", ""),
                        mime_hint=att_info.get("mime_hint", "application/octet-stream"),
                    )
                    if key in existing_keys:
                        attachments = [
                            a if a.get("key") != key else att_record for a in attachments
                        ]
                    else:
                        attachments.append(att_record)
                except Exception as e:
                    logger.warning(f"Failed to attach {key}: {e}")

        # 3. Finalize workflow with complete attachment records
        pm.save_workflow(
            module_id=module_id,
            payload=payload,
            metadata=metadata,
            filename=new_filename,
            attachments=attachments,
        )
        return new_filename
