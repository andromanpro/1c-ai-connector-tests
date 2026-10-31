"""Synthetic provider that initially overlooks the next page of object structure."""
import json

def reply(payload,scenario,check):
    messages=payload['messages'];results=[x for x in messages if x.get('role')=='tool']
    reminder=any(x.get('role')=='system' and 'Структура получена не полностью' in x.get('content','') for x in messages)
    if not results:
        arguments={'object_type':'Catalog','name':'КИИ_МоделиИИ','limit':2,'offset':2 if scenario=='structure-tail' else 0}
    elif scenario=='structure-stubborn' or not reminder:
        return answer({'role':'assistant','content':'STRUCTURE_COMPLETE'},'stop')
    elif len(results)==1:
        page=json.loads(results[-1]['content'])
        check(page['has_more'] is True,'first_structure_page_is_incomplete')
        arguments={'object_type':'Catalog','name':'КИИ_МоделиИИ','limit':200,'offset':page['next_offset']}
    else:
        first=json.loads(results[0]['content']);last=json.loads(results[-1]['content'])
        check(last['offset']==first['next_offset'],'structure_continuation_has_no_gap')
        check(last['has_more'] is False,'complete_structure_reaches_final_answer')
        return answer({'role':'assistant','content':'STRUCTURE_COMPLETE'},'stop')
    call={'id':'structure-'+str(len(results)),'type':'function','function':{'name':'get_object_structure','arguments':json.dumps(arguments,ensure_ascii=False)}}
    return answer({'role':'assistant','content':None,'tool_calls':[call]},'tool_calls')

def answer(message,finish):
    return {'choices':[{'message':message,'finish_reason':finish}], 'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
