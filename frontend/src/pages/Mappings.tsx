import {useEffect,useState} from 'react';
import {get,post} from '../lib/api';

export default function Mappings(){
 const [rows,setRows]=useState<any[]>([]); const [isin,setIsin]=useState(''); const [security,setSecurity]=useState(''); const [symbol,setSymbol]=useState(''); const [err,setErr]=useState('');
 const load=()=>get<any>('/instrument-mappings').then(x=>setRows(x.items||[])).catch(e=>setErr(e.message));
 useEffect(load,[]);
 const save=async()=>{setErr('');try{await post('/instrument-mappings',{isin,security,yahoo_symbol:symbol});setIsin('');setSecurity('');setSymbol('');load()}catch(e:any){setErr(e.message||'Could not save mapping')}};
 return <div className="page"><div className="eyebrow">MARKET DATA</div><h1>Live Market Prices</h1><p className="muted">Prices are fetched from Yahoo Finance. No broker account, API key, or trading account is required. Yahoo ticker mappings are optional; the app attempts to find NSE symbols automatically.</p><div className="card form"><input placeholder="ISIN" value={isin} onChange={e=>setIsin(e.target.value)}/><input placeholder="Security name" value={security} onChange={e=>setSecurity(e.target.value)}/><input placeholder="Yahoo symbol, e.g. SBIN.NS" value={symbol} onChange={e=>setSymbol(e.target.value)}/><button disabled={!isin||!symbol} onClick={save}>Save Yahoo mapping</button></div>{err&&<div className="alert high">{err}</div>}<div className="card"><table><thead><tr><th>ISIN</th><th>Security</th><th>Yahoo Symbol</th></tr></thead><tbody>{rows.map(r=><tr key={`${r.isin}-${r.provider}`}><td>{r.isin}</td><td>{r.security}</td><td>{r.instrument_key}</td></tr>)}</tbody></table></div></div>
}
