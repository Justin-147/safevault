from __future__ import annotations

from contextlib import suppress
from importlib.resources import files
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from safevault.config import VALID_PROFILES
from safevault.errors import SafeVaultError
from safevault.ui import services
from safevault.ui.auth import UI_COOKIE_NAME, require_token

templates = Jinja2Templates(directory=str(files("safevault.ui").joinpath("templates")))


def _render(
    request: Request,
    template: str,
    token: str,
    *,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    payload: dict[str, object] = {
        "request": request,
        "token": token,
        "local_warning": "Local UI only. Not a remote admin console.",
    }
    payload.update(context)
    response = templates.TemplateResponse(request, template, payload, status_code=status_code)
    if request.query_params.get("token") == token:
        response.set_cookie(UI_COOKIE_NAME, token, httponly=True, samesite="lax")
    return response


def _error_message(exc: Exception) -> str:
    return f"Error: {exc}"


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        q: str = "",
        deleted: bool = False,
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        try:
            if services.should_show_onboarding():
                return _render(
                    request,
                    "onboarding.html",
                    token,
                    candidates=services.onboarding_candidates_for_ui(),
                )
            status = services.get_dashboard_status()
            return _render(
                request,
                "dashboard.html",
                token,
                status=status,
                recent_deleted=services.list_deleted_for_ui("7d")[:10],
                recent_modified=services.list_recent_modified_for_ui("7d")[:10],
                search_query=q,
                search_deleted=deleted,
                search_results=services.search_for_ui(q, deleted=deleted),
                backup_status=services.backup_status_for_ui(),
            )
        except SafeVaultError as exc:
            return _render(request, "dashboard.html", token, error=_error_message(exc))

    @router.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(
        request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        return _render(
            request,
            "onboarding.html",
            token,
            candidates=services.onboarding_candidates_for_ui(),
        )

    @router.post("/onboarding", response_class=HTMLResponse)
    async def onboarding_complete(
        request: Request,
        backup_target: str = Form(""),
        backup_schedule: str = Form("daily"),
        skip_roots: bool = Form(False),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message = None
        error = None
        try:
            form = await request.form()
            roots = [str(value) for value in form.getlist("roots")]
            result = services.complete_onboarding_from_ui(
                roots=roots,
                backup_target=backup_target,
                backup_schedule=backup_schedule,
                skip_roots=skip_roots,
            )
            message = (
                f"Onboarding complete. Roots: {len(result['roots'])}; "
                f"initial snapshots: {len(result['snapshots'])}"
            )
            status = services.get_dashboard_status()
            return _render(
                request,
                "dashboard.html",
                token,
                status=status,
                recent_deleted=services.list_deleted_for_ui("7d")[:10],
                recent_modified=services.list_recent_modified_for_ui("7d")[:10],
                search_query="",
                search_deleted=False,
                search_results=[],
                backup_status=services.backup_status_for_ui(),
                message=message,
            )
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request,
            "onboarding.html",
            token,
            candidates=services.onboarding_candidates_for_ui(),
            error=error,
        )

    @router.get("/roots", response_class=HTMLResponse)
    def roots_page(request: Request, token: str = Depends(require_token)) -> HTMLResponse:
        return _render(
            request,
            "roots.html",
            token,
            roots=services.list_roots_for_ui(),
            profiles=sorted(VALID_PROFILES),
        )

    @router.post("/roots/add", response_class=HTMLResponse)
    def add_root(
        request: Request,
        path: str = Form(...),
        profile: str = Form("coding"),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message = None
        error = None
        try:
            root_id = services.add_root_from_ui(Path(path), profile)
            message = f"Protected root {root_id}"
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request,
            "roots.html",
            token,
            roots=services.list_roots_for_ui(),
            profiles=sorted(VALID_PROFILES),
            message=message,
            error=error,
        )

    @router.get("/roots/{root_id}", response_class=HTMLResponse)
    def root_detail(
        root_id: int, request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        try:
            detail = services.get_root_detail(root_id)
            return _render(request, "root_detail.html", token, detail=detail)
        except SafeVaultError as exc:
            return _render(request, "root_detail.html", token, error=_error_message(exc))

    @router.post("/roots/{root_id}/snapshot", response_class=HTMLResponse)
    def root_snapshot(
        root_id: int,
        request: Request,
        reason: str = Form("ui-manual"),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message = None
        error = None
        try:
            snapshot_id = services.run_snapshot_for_root(root_id, reason or "ui-manual")
            message = f"Snapshot {snapshot_id} complete"
            detail = services.get_root_detail(root_id)
        except SafeVaultError as exc:
            detail = None
            error = _error_message(exc)
        return _render(
            request, "root_detail.html", token, detail=detail, message=message, error=error
        )

    @router.post("/roots/{root_id}/unprotect", response_class=HTMLResponse)
    def root_unprotect(
        root_id: int,
        request: Request,
        mode: str = Form("dry-run"),
        confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message = None
        error = None
        plan = None
        try:
            if mode == "confirm":
                plan = services.unprotect_from_ui(root_id, confirmation)
                message = "Root metadata removed. Object-store files were not deleted."
                detail = None
            else:
                plan = services.plan_unprotect_from_ui(root_id)
                detail = services.get_root_detail(root_id)
        except SafeVaultError as exc:
            detail = None
            error = _error_message(exc)
        return _render(
            request,
            "root_detail.html",
            token,
            detail=detail,
            plan=plan,
            message=message,
            error=error,
        )

    @router.get("/versions", response_class=HTMLResponse)
    def versions_page(
        request: Request,
        file: str = "",
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        versions = []
        error = None
        if file:
            try:
                versions = services.list_versions_for_file(Path(file))
            except SafeVaultError as exc:
                error = _error_message(exc)
        return _render(
            request, "versions.html", token, file=file, versions=versions, error=error
        )

    @router.post("/restore", response_class=HTMLResponse)
    def restore_action(
        request: Request,
        file: str = Form(...),
        mode: str = Form("latest"),
        version_id: int | None = Form(None),
        to_path: str = Form(""),
        confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message = None
        error = None
        try:
            target = services.restore_from_ui(
                Path(file),
                latest=mode == "latest",
                version_id=None if mode == "latest" else version_id,
                to_path=Path(to_path) if to_path else None,
                confirmation=confirmation,
            )
            message = f"Restored to {target}"
        except SafeVaultError as exc:
            error = _error_message(exc)
        versions = []
        with suppress(SafeVaultError):
            versions = services.list_versions_for_file(Path(file))
        return _render(
            request,
            "versions.html",
            token,
            file=file,
            versions=versions,
            message=message,
            error=error,
        )

    @router.get("/deleted", response_class=HTMLResponse)
    def deleted_page(
        request: Request,
        since: str = "24h",
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        error = None
        entries = []
        try:
            entries = services.list_deleted_for_ui(since)
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request, "deleted.html", token, since=since, entries=entries, error=error
        )

    @router.get("/sandboxes", response_class=HTMLResponse)
    def sandboxes_page(request: Request, token: str = Depends(require_token)) -> HTMLResponse:
        return _render(
            request, "sandboxes.html", token, sandboxes=services.list_sandboxes_for_ui()
        )

    @router.get("/sandboxes/{sandbox_id}", response_class=HTMLResponse)
    def sandbox_detail(
        sandbox_id: str, request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        try:
            sandbox, diff = services.get_sandbox_diff(sandbox_id)
            return _render(
                request, "sandbox_detail.html", token, sandbox=sandbox, diff=diff
            )
        except SafeVaultError as exc:
            return _render(request, "sandbox_detail.html", token, error=_error_message(exc))

    @router.post("/sandboxes/{sandbox_id}/apply", response_class=HTMLResponse)
    def sandbox_apply(
        sandbox_id: str,
        request: Request,
        dry_run: bool = Form(False),
        allow_delete: bool = Form(False),
        delete_confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        result = None
        error = None
        try:
            result = services.apply_sandbox_from_ui(
                sandbox_id,
                allow_delete=allow_delete,
                dry_run=dry_run,
                confirmation=delete_confirmation,
            )
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request,
            "apply_result.html",
            token,
            sandbox_id=sandbox_id,
            result=result,
            error=error,
        )

    @router.get("/maintenance", response_class=HTMLResponse)
    def maintenance_page(
        request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        return _render(request, "maintenance.html", token)

    @router.post("/maintenance", response_class=HTMLResponse)
    def maintenance_action(
        request: Request,
        action: str = Form(...),
        confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        message: str | None = None
        error: str | None = None
        result: object | None = None
        try:
            if action == "doctor-fast":
                result = services.run_doctor_for_ui(deep=False)
            elif action == "doctor-deep":
                result = services.run_doctor_for_ui(deep=True)
            elif action == "verify-fast":
                result = services.run_verify_for_ui(deep=False)
            elif action == "verify-deep":
                result = services.run_verify_for_ui(deep=True)
            elif action == "prune-dry-run":
                result = services.prune_from_ui(dry_run=True)
            elif action == "prune-confirm":
                result = services.prune_from_ui(dry_run=False, confirmation=confirmation)
            elif action == "sandbox-clean-dry-run":
                result = services.sandbox_clean_from_ui(dry_run=True, confirm=False)
            elif action == "sandbox-clean-confirm":
                result = services.sandbox_clean_from_ui(
                    dry_run=False, confirm=True, confirmation=confirmation
                )
            elif action == "retention-plan":
                result = services.retention_plan_for_ui()
            else:
                raise SafeVaultError(f"unknown maintenance action: {action}")
            message = f"{action} complete"
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request,
            "maintenance.html",
            token,
            action=action,
            result=result,
            message=message,
            error=error,
        )

    @router.get("/export-import", response_class=HTMLResponse)
    def export_import_page(
        request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        return _render(request, "export_import.html", token)

    @router.post("/backup/run", response_class=HTMLResponse)
    def backup_run_action(
        request: Request, token: str = Depends(require_token)
    ) -> HTMLResponse:
        message = None
        error = None
        try:
            result = services.run_backup_from_ui()
            message = f"Backup complete: {result.output}"
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request,
            "dashboard.html",
            token,
            status=services.get_dashboard_status(),
            recent_deleted=services.list_deleted_for_ui("7d")[:10],
            recent_modified=services.list_recent_modified_for_ui("7d")[:10],
            search_query="",
            search_deleted=False,
            search_results=[],
            backup_status=services.backup_status_for_ui(),
            message=message,
            error=error,
        )

    @router.post("/export-import/export", response_class=HTMLResponse)
    def export_action(
        request: Request,
        output: str = Form(...),
        gzip: bool = Form(False),
        overwrite: bool = Form(False),
        skip_verify: bool = Form(False),
        allow_inside_vault: bool = Form(False),
        overwrite_confirmation: str = Form(""),
        skip_verify_confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        result = None
        error = None
        try:
            result = services.export_from_ui(
                output=Path(output),
                gzip=gzip,
                overwrite=overwrite,
                skip_verify=skip_verify,
                allow_inside_vault=allow_inside_vault,
                overwrite_confirmation=overwrite_confirmation,
                skip_verify_confirmation=skip_verify_confirmation,
            )
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request, "export_import.html", token, export_result=result, error=error
        )

    @router.post("/export-import/import", response_class=HTMLResponse)
    def import_action(
        request: Request,
        input_path: str = Form(...),
        target_home: str = Form(...),
        dry_run: bool = Form(False),
        confirm: bool = Form(False),
        overwrite: bool = Form(False),
        import_confirmation: str = Form(""),
        overwrite_confirmation: str = Form(""),
        token: str = Depends(require_token),
    ) -> HTMLResponse:
        result = None
        error = None
        try:
            result = services.import_from_ui(
                input_path=Path(input_path),
                target_home=Path(target_home),
                dry_run=dry_run,
                confirm=confirm,
                overwrite=overwrite,
                import_confirmation=import_confirmation,
                overwrite_confirmation=overwrite_confirmation,
            )
        except SafeVaultError as exc:
            error = _error_message(exc)
        return _render(
            request, "export_import.html", token, import_result=result, error=error
        )

    @router.get("/help", response_class=HTMLResponse)
    def help_page(request: Request, token: str = Depends(require_token)) -> HTMLResponse:
        return _render(request, "help.html", token)

    @router.get("/docs/zh/{doc_name}", response_class=PlainTextResponse)
    def zh_doc(
        doc_name: str, request: Request, token: str = Depends(require_token)
    ) -> PlainTextResponse:
        _ = (request, token)
        allowed = {
            "USER_MANUAL.md",
            "GUI_GUIDE.md",
            "RECOVERY_PLAYBOOK.md",
            "CODEX_WORKFLOW.md",
            "FAQ.md",
            "TROUBLESHOOTING.md",
            "SAFETY_MODEL.md",
            "auto-protection.md",
            "daemon-tray.md",
            "one-click-restore.md",
            "automatic-backup.md",
            "onboarding.md",
        }
        if doc_name not in allowed:
            return PlainTextResponse("Not found", status_code=404)
        docs_root = Path.cwd() / "docs" / "zh"
        path = docs_root / doc_name
        if not path.is_file():
            resource = files("safevault.ui").joinpath("docs", "zh", doc_name)
            if not resource.is_file():
                return PlainTextResponse("Not found", status_code=404)
            return PlainTextResponse(resource.read_text(encoding="utf-8"))
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    return router
