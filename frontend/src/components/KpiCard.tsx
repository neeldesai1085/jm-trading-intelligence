export default function KpiCard({label,value,sub}:{label:string,value:any,sub?:string}){return <div className="kpi"><span>{label}</span><strong>{value}</strong>{sub&&<small>{sub}</small>}</div>}
