"""Run local input diagnostics and optional provider smoke checks; never print keys."""
import argparse
import json
import os
from pathlib import Path

from .data import DataStore
from .engine import Engine


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--providers',action='store_true')
    args=p.parse_args()
    config=Path.home()/'.config/heatahead/assistant.env'
    if args.providers and config.is_file():
        for line in config.read_text().splitlines():
            key,sep,value=line.partition('=')
            if sep and key.strip() in ('LLM_BASE_URL','LLM_API_KEY','LLM_MODEL','TAVILY_API_KEY'):
                os.environ.setdefault(key.strip(),value.strip().strip('"\''))
    store=DataStore(args.root)
    print(json.dumps(store.analyze(operation='catalog')['metadata'],indent=2))
    try:
        result=store.analyze(operation='forecast',days=3)
        output=args.root/'data/assistant/input_forecast_check.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2))
        print('Experimental forecast check saved:',output)
        print('Backtest:',json.dumps({k:result['forecast'][k] for k in ('quality','test_interval_coverage','model_test_mae','baseline_test_mae')}))
    except ValueError as exc:
        print('Forecast unavailable:',str(exc))
    if args.providers:
        # Explicit opt-in; consumes a model request and one basic search credit.
        engine=Engine(store,lambda k:None)
        answer=engine.model_call([{'role':'user','content':'Reply only with OK.'}],tools=False)
        print('Model response present:',bool(answer.get('content')))
        tool=engine.model_call([{'role':'user','content':'Use analyze_complaints with operation catalog to inspect the dataset. Do not answer without calling the tool.'}])
        print('Function call produced:',bool(tool.get('tool_calls')))
        rows=engine.search_call('site.nyc.gov HPD heat complaints NYC311')
        print('Search result count:',len(rows))


if __name__=='__main__':main()
