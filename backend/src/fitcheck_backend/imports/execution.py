import asyncio
from pydantic import ValidationError
from ..contracts.imports import LocalImportRequest,parse_import_row
from ..storage.import_repository import ImportRepository
from ..storage.job_queue import job_transaction


class ImportExecutor:
    def __init__(self,engine):self.engine=engine

    def _transaction(self,method,*args):
        with job_transaction(self.engine) as session:
            return getattr(ImportRepository(session),method)(*args)

    async def execute(self,lease):
        if lease.type!='import':raise ValueError('Invalid import lease')
        request=LocalImportRequest.model_validate(lease.input)
        await asyncio.to_thread(self._transaction,'apply_profile',lease,request)
        await asyncio.to_thread(self._transaction,'apply_preferences',lease,request)
        for index,raw in enumerate(request.history):
            try:row=parse_import_row(raw)
            except ValidationError:
                await asyncio.to_thread(self._transaction,'record_invalid',lease,index)
            else:
                await asyncio.to_thread(self._transaction,'apply_row',lease,index,row)
        return await asyncio.to_thread(self._transaction,'report',lease.job_id,lease.owner_id)
