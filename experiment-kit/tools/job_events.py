"""Read current Job journals and explicitly migrate historical Entity records in memory."""
def normalize(row):
    result=dict(row)
    if 'entity' in result:
        if 'job' in result and result['job']!=result['entity']:
            raise ValueError('Conflicting legacy Entity and Job evidence')
        result['job']=result.pop('entity')
    event=result.get('event','')
    if event.startswith('entity_execution_'):
        result['event']='job_execution_'+event[len('entity_execution_'):]
    return result
