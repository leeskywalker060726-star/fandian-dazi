export type User = {id:string;username:string;guest:boolean;onboarded:boolean;version:number;memory_enabled:boolean;settings:Record<string,unknown>}
export type MemoryFact={id:string;key:string;value:string|number;label:string;scope:string;source:string;quote:string;expires_at:string|null}
export type NarrativeMemory={id:string;title:string;content:string;quote:string;source:string;scope:string;status:string;expires_at:string|null}
export type Memories={version:number;enabled:boolean;facts:MemoryFact[];overview:string;narratives:NarrativeMemory[];pending:NarrativeMemory[]}
export type Context={weather:'sunny'|'rainy';hour:number;location:string;available_minutes:number|null;source:string}
export type Food={id:string;name:string;vendor:string;vendor_id:string;channel:string;category:string;total_cents:number;total_min:number;price_cents:number;delivery_cents:number;packaging_cents:number;party_size:number;reasons:string[];tags:string[];art:string;time_parts:Record<string,number>;ingredients:string[];allergens:string[];source:string}
export type Conversation={id:string;version:number;state:Record<string,unknown>;messages:{id:string;role:string;content:string;notices?:string[]}[];recommendations:Food[];closed:boolean;model_mode?:string;reply_mode?:string;response_kind?:string;catalog_mode?:string;constraints?:Record<string,unknown>}
export type Meal={id:string;food:Food;eaten:boolean;actual_cents:number|null;feedback:string;created_at:string}
