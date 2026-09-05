export const API=import.meta.env.VITE_API_URL||'/api';
async function request(path:string,init:RequestInit={}){
 const r=await fetch(API+path,init);
 if(!r.ok){let detail='Request failed';try{const body=await r.json();detail=body.detail||JSON.stringify(body)}catch{detail=await r.text()||detail}throw new Error(detail)}
 return r.status===204?null:r.json();
}
export async function get<T=any>(path:string):Promise<T>{return request(path)}
export async function upload(files:File[]):Promise<any>{const f=new FormData();files.forEach(x=>f.append('files',x));return request('/imports/upload',{method:'POST',body:f})}
