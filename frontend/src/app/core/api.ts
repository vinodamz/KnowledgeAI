import {Injectable,signal} from '@angular/core';
import {Actor,Profile,Version,Context,Schema} from './contracts';
export class ApiError extends Error {constructor(public status:number,message:string){super(message);}}
@Injectable({providedIn:'root'})
export class Api {
 actor=signal<Actor|null>(null);ready=signal(false);error=signal('');notice=signal('');busy=signal(false);
 profiles=signal<Profile[]>([]);versions=signal<Version[]>([]);contexts=signal<Context[]>([]);
 profileId=signal(sessionStorage.getItem('ka-profile')||'');versionId=signal(sessionStorage.getItem('ka-version')||'');
 private csrf='';
 get profile(){return this.profiles().find(p=>p.id===this.profileId());}
 get version(){return this.versions().find(v=>v.id===this.versionId());}
 get isAdmin(){return this.actor()?.role==='admin';}
 get canOwn(){return !!this.profile&&this.profile.owner_id===this.actor()?.id&&['owner','admin'].includes(this.actor()?.role||'');}
 get canEdit(){return this.isAdmin||this.canOwn||!!this.actor()?.contribute_profile_ids.includes(this.profileId());}
 async request<T>(path:string,method='GET',body?:unknown):Promise<T>{
  const headers:Record<string,string>={};if(body!==undefined&&!(body instanceof FormData))headers['Content-Type']='application/json';
  if(method!=='GET')headers['X-CSRF-Token']=this.csrf;
  const r=await fetch('/api'+path,{method,credentials:'same-origin',headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});
  if(!r.ok){const data=await r.json().catch(()=>({detail:'Request failed'}));if(r.status===401)this.actor.set(null);throw new ApiError(r.status,typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));}
  return (r.status===204?undefined:await r.json()) as T;
 }
 async run(action:()=>Promise<void>){this.error.set('');this.notice.set('');this.busy.set(true);try{await action();}catch(e){this.error.set(e instanceof ApiError&&e.status===409?e.message+' Your view has not been overwritten. Refresh and compare before trying again.':e instanceof Error?e.message:'Unable to complete request');}finally{this.busy.set(false);}}
 async init(){try{this.actor.set(await this.request<Actor>('/auth/me'));this.csrf=(await this.request<{csrf_token:string}>('/auth/csrf')).csrf_token;await this.reload();}catch(e){if(!(e instanceof ApiError&&e.status===401))this.error.set(String(e));}finally{this.ready.set(true);}}
 async login(username:string,password:string){const body:Schema<'Credentials'>={username,password};const r=await this.request<{csrf_token:string}>('/auth/login','POST',body);this.csrf=r.csrf_token;this.actor.set(await this.request<Actor>('/auth/me'));await this.reload();}
 async logout(){await this.request('/auth/logout','POST');this.actor.set(null);this.csrf='';this.profiles.set([]);this.versions.set([]);this.contexts.set([]);}
 async reload(){this.profiles.set(await this.request<Profile[]>('/profiles'));this.contexts.set(await this.request<Context[]>('/available-contexts'));if(!this.profiles().some(p=>p.id===this.profileId()))this.profileId.set(this.profiles()[0]?.id||'');await this.selectProfile(this.profileId());}
 async selectProfile(id:string){this.profileId.set(id);sessionStorage.setItem('ka-profile',id);this.versions.set(id?await this.request<Version[]>(`/profiles/${id}/versions`):[]);if(!this.versions().some(v=>v.id===this.versionId()))this.selectVersion(this.versions()[0]?.id||'');}
 selectVersion(id:string){this.versionId.set(id);sessionStorage.setItem('ka-version',id);}
}
