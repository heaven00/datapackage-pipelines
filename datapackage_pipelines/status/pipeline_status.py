from typing import Optional

import logging

from .hook_sender import hook_sender
from .pipeline_execution import PipelineExecution


class PipelineStatus(object):

    def __init__(self, backend,
                 pipeline_id):
        self.backend = backend
        self.pipeline_id = pipeline_id
        self.__load()

    def init(self,
             pipeline_details,
             source_spec,
             validation_errors,
             cache_hash):
        self.pipeline_details = pipeline_details
        self.source_spec = source_spec
        self.validation_errors = validation_errors
        self.cache_hash = cache_hash
        self.backend.register_pipeline_id(self.pipeline_id)
        self.__save()

    def __load(self):
        data = self.backend.get_status('PipelineStatus:' + self.pipeline_id)
        if data is None:
            data = {}
        self.pipeline_details = data.get('pipeline_details', {})
        self.source_spec = data.get('source_spec', {})
        self.validation_errors = data.get('validation_errors', [])
        self.cache_hash = data.get('cache_hash', '')
        self.executions = [PipelineExecution.from_execution_id(self.backend, ex)
                           for ex in data.get('executions', [])]

    def __iter__(self):
        yield 'pipeline_details', self.pipeline_details,
        yield 'source_spec', self.source_spec,
        yield 'validation_errors', self.validation_errors
        yield 'cache_hash', self.cache_hash
        yield 'executions', [ex.execution_id for ex in self.executions]

    def __save(self):
        # logging.debug('SAVING PipelineStatus %s -> %r' % (self.pipeline_id, self.executions))
        self.backend.set_status('PipelineStatus:' + self.pipeline_id, dict(self))

    def dirty(self):
        return len(self.executions) == 0 or self.cache_hash != self.executions[0].cache_hash

    def errors(self):
        if not self.runnable():
            return ['%s :%s' % tuple(err)
                    for err in self.validation_errors]
        else:
            ex = self.get_last_execution()
            if ex is not None:
                return ex.error_log
        return []

    def runnable(self):
        return len(self.validation_errors) == 0

    def get_last_execution(self) -> Optional[PipelineExecution]:
        if len(self.executions) == 0:
            return None
        return self.executions[0]

    def get_last_successful_execution(self) -> Optional[PipelineExecution]:
        for ex in self.executions:
            if ex.success:
                return ex
        return None

    def queue_execution(self, execution_id, trigger):
        last_exec = self.get_last_execution()
        if last_exec is not None and last_exec.finish_time is None:
            logging.info('%s %s is ALREADY RUNNING, BAILING', execution_id[:8], self.pipeline_id)
            return False
        # for ex in self.executions:  # type: PipelineExecution
        #     if not ex.invalidate():
        #         break
        execution = PipelineExecution(self.backend,
                                      self.pipeline_id, self.pipeline_details, self.cache_hash,
                                      trigger, execution_id, save=False)
        assert execution.queue_execution(trigger)
        self.executions.insert(0, execution)
        while len(self.executions) > 10:
            last = self.executions.pop()  # type: PipelineExecution
            last.delete()
        self.__save()
        self.update_hooks('queue', blocking=True)
        return True

    def validate_execution_id(self, execution_id):
        if len(self.executions) == 0:
            logging.info('%s NO EXISTING EXECUTIONS', execution_id[:8])
            return False
        first = self.executions[0].execution_id
        if first != execution_id:
            logging.info('%s EXECUTION ID MISMATCH (first: %s)', execution_id[:8], first)
            return False
        return True

    def start_execution(self, execution_id):
        if not self.validate_execution_id(execution_id):
            return False
        self.update_hooks('start')
        return self.executions[0].start_execution()

    def finish_execution(self, execution_id, success, stats, error_log):
        if self.validate_execution_id(execution_id):
            self.update_hooks('finish', success=success, errors=error_log, stats=stats)
            return self.executions[0].finish_execution(success, stats, error_log)
        return False

    def update_execution(self, execution_id, log, hooks=False):
        if self.validate_execution_id(execution_id):
            if hooks:
                self.update_hooks('progress', log=log)
            return self.executions[0].update_execution(log)
        return False

    def deregister(self):
        self.backend.deregister_pipeline_id(self.pipeline_id)

    def state(self):
        if not self.runnable():
            return 'INVALID'
        last_execution = self.get_last_execution()
        if last_execution is None:
            return 'INIT'
        if last_execution.success is None:
            if last_execution.start_time is None:
                return 'QUEUED'
            else:
                return 'RUNNING'
        if last_execution.success:
            return 'SUCCEEDED'
        else:
            return 'FAILED'

    def update_hooks(self, event, *, success=None, errors=None, stats=None, log=None, blocking=False):
        hooks = self.pipeline_details.get('hooks')
        if hooks is not None:
            payload = {
                'pipeline_id': self.pipeline_id,
                'event': event,
            }
            if success is not None:
                payload['success'] = success
            if errors is not None:
                payload['errors'] = errors
            if stats is not None:
                payload['stats'] = stats
            if log is not None:
                payload['log'] = log[-100:]
            for hook in hooks:
                hook_sender.send(hook, payload, blocking=blocking)
