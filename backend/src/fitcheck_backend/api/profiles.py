from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Request, Response

from ..contracts import resources as r
from ..contracts.openapi import ERRORS, SECURITY
from .dependencies import required_runtime, verified_principal, validate_account_mutation
from .errors import ApiError, ErrorEnvelope

router = APIRouter(dependencies=[Depends(required_runtime)],
    responses={status: {'model': ErrorEnvelope, 'description': code} for status, code in ERRORS.items()})


def metadata(*, mutation=False):
    value = {'x-fitcheck-owner-task': 'ANY-646', 'x-fitcheck-implementation': 'implemented',
        'security': SECURITY['account']}
    if mutation:
        value['x-fitcheck-cookie-mutation'] = {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'}
        value['parameters'] = [
            {'name': 'Origin', 'in': 'header', 'required': True, 'schema': {'type': 'string'}},
            {'name': 'X-CSRF-Token', 'in': 'header', 'required': False, 'schema': {'type': 'string'},
             'description': 'Required for web cookie sessions.'}]
    return value


def mutation_principal(request: Request, principal=Depends(verified_principal)):
    validate_account_mutation(request, principal)
    return principal


async def required_draft_body(request: Request):
    # FastAPI treats JSON null like an absent required body. Allow null explicitly,
    # while retaining the distinction between clearing and a missing request body.
    if not (await request.body()).strip():
        raise ApiError(400, 'invalid_request', 'Draft body is required; send null to clear it')


@router.get('/v1/profile', response_model=r.ProfileResource, operation_id='getProfile', openapi_extra=metadata())
def get_profile(request: Request, principal=Depends(verified_principal)):
    return required_runtime(request).profiles.get(principal)


@router.put('/v1/profile', response_model=r.ProfileResource, operation_id='updateProfile', openapi_extra=metadata(mutation=True))
def update_profile(body: r.ProfileUpdate, request: Request, principal=Depends(mutation_principal)):
    return required_runtime(request).profiles.update(principal, body)


@router.get('/v1/profile/revisions/{revision}', response_model=r.ProfileResource,
    operation_id='getProfileRevision', openapi_extra=metadata())
def get_revision(revision: Annotated[r.ProfileRevisionNumber, Path()], request: Request,
    principal=Depends(verified_principal)):
    return required_runtime(request).profiles.get(principal, int(revision))


@router.get('/v1/profile/revisions/{revision}/comparison', response_model=r.ProfileComparison,
    operation_id='compareProfileRevision', openapi_extra=metadata())
def compare_revision(revision: Annotated[r.ProfileRevisionNumber, Path()], request: Request,
    principal=Depends(verified_principal)):
    return required_runtime(request).profiles.compare(principal, int(revision))


@router.get('/v1/preferences', response_model=r.Preferences, operation_id='getPreferences', openapi_extra=metadata())
def get_preferences(request: Request, principal=Depends(verified_principal)):
    return required_runtime(request).profiles.get_preferences(principal)


@router.put('/v1/preferences', response_model=r.Preferences, operation_id='updatePreferences', openapi_extra=metadata(mutation=True))
def update_preferences(body: r.Preferences, request: Request, principal=Depends(mutation_principal)):
    return required_runtime(request).profiles.update_preferences(principal, body)


@router.get('/v1/draft', response_model=r.DraftResponse, operation_id='getDraft', openapi_extra=metadata())
def get_draft(request: Request, principal=Depends(verified_principal)):
    return r.DraftResponse(required_runtime(request).profiles.get_draft(principal))


@router.put('/v1/draft', response_model=r.DraftResponse, operation_id='updateDraft',
    openapi_extra={**metadata(mutation=True), 'requestBody': {'required': True}})
def update_draft(request: Request, body: r.DraftResponse | None = Body(default=None),
    principal=Depends(mutation_principal), _=Depends(required_draft_body)):
    return r.DraftResponse(required_runtime(request).profiles.update_draft(principal, body.root if body is not None else None))


@router.delete('/v1/draft', status_code=204, operation_id='deleteDraft', openapi_extra=metadata(mutation=True))
def delete_draft(request: Request, principal=Depends(mutation_principal)):
    required_runtime(request).profiles.update_draft(principal, None)
    return Response(status_code=204)
