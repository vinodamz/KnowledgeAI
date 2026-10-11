import {Component,effect,inject,signal,untracked} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {Api} from '../core/api';
import {Model,Entity,Relation,Concept,Schema} from '../core/contracts';
@Component({selector:'ka-models',imports:[FormsModule],templateUrl:'./models.html'})
export class Models{
 api=inject(Api);models=signal<Model[]>([]);model=signal<Model|null>(null);description='';entityId='';entityName='';attributes:{name:string;data_type:string;description:string}[]=[];scores:Record<string,string>={};scoreFields=['identity','lifecycle','relationships','own_attributes','reuse','retrieval_rationale'];qualification='';relationId='';relationName='';sourceType='';targetType='';conceptId='';conceptName='';aliases='';links:string[]=[];linkModels=signal<(Model&{profileName:string})[]>([]);
 constructor(){effect(()=>{const id=this.api.profileId();untracked(()=>void this.api.run(()=>this.load(id)));});}
 get editable(){return this.api.canEdit&&this.model()?.status==='draft';}
 async load(id=this.api.profileId()){this.models.set(id?await this.api.request<Model[]>('/profiles/'+id+'/models'):[]);this.select(this.models().find(m=>m.id===this.model()?.id)||this.models().at(-1)||null);const lists=await Promise.all(this.api.profiles().filter(p=>p.id!==id).map(async p=>(await this.api.request<Model[]>('/profiles/'+p.id+'/models')).filter(m=>m.status==='published').map(m=>({...m,profileName:p.name}))));this.linkModels.set(lists.flat());}
 select(m:Model|null){this.model.set(m);this.description=m?.semantic_description||'';this.links=m?.target_model_revision_ids||[];this.resetEntity();}
 refresh(){void this.api.run(()=>this.load());}
 create(){void this.api.run(async()=>{const body:Schema<'ModelInput'>={semantic_description:this.description};const m=await this.api.request<Model>('/profiles/'+this.api.profileId()+'/models','POST',body);this.models.update(ms=>[...ms,m]);this.select(m);});}
 async mutation(path:string,method:string,body?:unknown){this.model.set(await this.api.request<Model>('/models/'+this.model()!.id+path,method,body));this.models.update(ms=>ms.map(m=>m.id===this.model()!.id?this.model()!:m));}
 saveDescription(){void this.api.run(async()=>{const body:Schema<'ModelInput'>={semantic_description:this.description};await this.mutation('','PATCH',body);});}
 resetEntity(){this.entityId='';this.entityName='';this.attributes=[];this.scores={};this.qualification='';}
 editEntity(e:Entity){this.entityId=e.id;this.entityName=e.name;this.attributes=structuredClone(e.attributes);this.scores=Object.fromEntries(Object.entries(e.scores).map(([k,v])=>[k,String(v)]));this.qualification=e.qualification||'';}
 saveEntity(){void this.api.run(async()=>{const scores=Object.fromEntries(Object.entries(this.scores).filter(([,v])=>v.trim()).map(([k,v])=>[k,k!=='retrieval_rationale'&&Number.isFinite(Number(v))?Number(v):v]));const body:Schema<'EntityInput'>={name:this.entityName,attributes:this.attributes,scores};await this.mutation('/entities'+(this.entityId?'/'+this.entityId:''),this.entityId?'PUT':'POST',body);this.resetEntity();});}
 qualify(e:Entity){void this.api.run(async()=>{const body:Schema<'Qualification'>={qualification:this.qualification};await this.mutation('/entities/'+e.id+'/qualification','PUT',body);});}
 editRelation(r:Relation){this.relationId=r.id;this.relationName=r.name;this.sourceType=r.source_type_id;this.targetType=r.target_type_id;}
 saveRelation(){void this.api.run(async()=>{const body:Schema<'RelationInput'>={name:this.relationName,source_type_id:this.sourceType,target_type_id:this.targetType};await this.mutation('/relations'+(this.relationId?'/'+this.relationId:''),this.relationId?'PUT':'POST',body);this.relationId='';this.relationName='';});}
 editConcept(c:Concept){this.conceptId=c.id;this.conceptName=c.name;this.aliases=c.aliases.join('\n');}
 saveConcept(){void this.api.run(async()=>{const old=this.model()?.concepts.find(c=>c.id===this.conceptId);const body:Schema<'ConceptInput'>={name:this.conceptName,aliases:this.aliases.split('\n').map(x=>x.trim()).filter(Boolean),provenance:old?.provenance||{}};await this.mutation('/concepts'+(this.conceptId?'/'+this.conceptId:''),this.conceptId?'PUT':'POST',body);this.conceptId='';this.conceptName='';this.aliases='';});}
 remove(kind:string,id:string){void this.api.run(()=>this.mutation('/'+kind+'/'+id,'DELETE'));}
 toggleLink(id:string){this.links=this.links.includes(id)?this.links.filter(x=>x!==id):[...this.links,id];}
 saveLinks(){void this.api.run(async()=>{const body:Schema<'Links'>={target_model_revision_ids:this.links};await this.mutation('/links','PUT',body);});}
 publish(){void this.api.run(async()=>{await this.mutation('/publish','POST');this.api.notice.set('Knowledge model published. Bind it to a draft knowledge version.');});}
 bind(){void this.api.run(async()=>{const body:Schema<'Binding'>={model_revision_id:this.model()!.id};await this.api.request('/versions/'+this.api.versionId()+'/model','PUT',body);await this.api.reload();this.api.notice.set('Published model bound to selected knowledge version.');});}
 findModel(id:string){return (m:Model)=>m.id===id;}
 typeName(id:string){return this.model()?.entities.find(e=>e.id===id)?.name||id;}
}
