import {Component,effect,inject,signal,untracked} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {RouterLink} from '@angular/router';
import {Api} from '../core/api';
import {User,Grant,Version,Schema} from '../core/contracts';
@Component({selector:'ka-profiles',imports:[FormsModule,RouterLink],templateUrl:'./profiles.html'})
export class Profiles{
 api=inject(Api);users=signal<User[]>([]);products=signal<(Version&{profileName:string})[]>([]);grants:Record<string,Grant>={};
 profileName='';kind:'product'|'project'='product';ownerId='';assignedOwner='';versionLabel='';predecessor='';pins:string[]=[];newUsername='';newPassword='';newRole:User['role']='reader';
 get owners(){return this.users().filter(u=>u.active&&['admin','owner'].includes(u.role));}
 constructor(){effect(()=>{const id=this.api.profileId();const version=this.api.versionId();untracked(()=>void this.load(id,version));});}
 async load(id:string,_version:string){await this.api.run(async()=>{if(this.api.isAdmin){const users=await this.api.request<User[]>('/users');for(const u of users)this.grants[u.id]={user_id:u.id,read:false,contribute:false};if(id)for(const g of await this.api.request<Grant[]>('/profiles/'+id+'/grants'))this.grants[g.user_id]=g;this.users.set(users);}this.assignedOwner=this.api.profile?.owner_id||'';this.pins=[...(this.api.version?.product_version_ids||[])];const ps=this.api.profiles().filter(p=>p.kind==='product');const vs=await Promise.all(ps.map(async p=>(await this.api.request<Version[]>('/profiles/'+p.id+'/versions')).map(v=>({...v,profileName:p.name}))));this.products.set(vs.flat());});}
 refresh(){void this.api.run(async()=>{await this.api.reload();await this.load(this.api.profileId(),this.api.versionId());});}
 select(id:string){void this.api.run(()=>this.api.selectProfile(id));}
 createProfile(){void this.api.run(async()=>{const body:Schema<'ProfileInput'>={name:this.profileName,kind:this.kind,owner_id:this.ownerId};await this.api.request('/profiles','POST',body);this.profileName='';await this.api.reload();});}
 createVersion(){void this.api.run(async()=>{const body:Schema<'VersionInput'>={label:this.versionLabel,predecessor_id:this.predecessor||null};const v=await this.api.request<Version>('/profiles/'+this.api.profileId()+'/versions','POST',body);await this.api.selectProfile(this.api.profileId());this.api.selectVersion(v.id);this.versionLabel='';});}
 togglePin(id:string){this.pins=this.pins.includes(id)?this.pins.filter(x=>x!==id):[...this.pins,id];}
 savePins(){void this.api.run(async()=>{const body:Schema<'Pins'>={product_version_ids:this.pins};await this.api.request('/versions/'+this.api.versionId()+'/dependencies','PUT',body);await this.api.reload();this.api.notice.set('Exact dependency pins saved.');});}
 assignOwner(){void this.api.run(async()=>{const body:Schema<'ProfilePatch'>={owner_id:this.assignedOwner};await this.api.request('/profiles/'+this.api.profileId(),'PATCH',body);await this.api.reload();});}
 saveGrant(id:string){void this.api.run(async()=>{const body:Schema<'Grant'>={read:this.grants[id].read,contribute:this.grants[id].contribute};await this.api.request('/profiles/'+this.api.profileId()+'/grants/'+id,'PUT',body);this.api.notice.set('Profile grant saved.');});}
 createUser(){void this.api.run(async()=>{const body:Schema<'UserInput'>={username:this.newUsername,password:this.newPassword,role:this.newRole};await this.api.request('/users','POST',body);this.newUsername='';this.newPassword='';await this.load(this.api.profileId(),this.api.versionId());});}
 toggleUser(u:User){void this.api.run(async()=>{const body:Schema<'UserPatch'>={active:!u.active};await this.api.request('/users/'+u.id,'PATCH',body);await this.load(this.api.profileId(),this.api.versionId());});}
}
