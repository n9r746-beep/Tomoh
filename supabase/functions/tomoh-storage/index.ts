import { createClient } from "npm:@supabase/supabase-js@2.49.8";
const expectedHash = "e26da30ff54f6544b4bc19f04ea10a3a3cb1f920398f7ce7c8c72c1b63ff0960";
const client=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,{auth:{persistSession:false}});
Deno.serve(async(req)=>{
 if(req.method!=="POST") return new Response("Method not allowed",{status:405});
 const token=req.headers.get("x-tomoh-token")||"";
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(token)))).map(x=>x.toString(16).padStart(2,"0")).join("");
 if(hash!==expectedHash) return new Response("Unauthorized",{status:401});
 try {
 const body=await req.json(); const {bucket,path,action}=body;
 if(!["tomoh-templates","tomoh-reports","tomoh-uploads","tomoh-attachments"].includes(bucket)||typeof path!=="string"||path.includes("..")||path.startsWith("/")||path.length>250) return new Response("Invalid object",{status:400});
 if(action==="upload"){
  if(typeof body.data!=="string"||body.data.length>71000000) return new Response("Invalid size",{status:413});
  const bytes=Uint8Array.from(atob(body.data),c=>c.charCodeAt(0));
  const {error}=await client.storage.from(bucket).upload(path,bytes,{contentType:body.content_type,upsert:true});
  if(error) throw error;return Response.json({ok:true});
 }
 if(action==="download"){
  const {data,error}=await client.storage.from(bucket).download(path);if(error) throw error;return new Response(data,{headers:{"Content-Type":data.type}});
 }
 if(action==="sign"){
  const {data,error}=await client.storage.from(bucket).createSignedUrl(path,300,{download:true});if(error) throw error;return Response.json({url:data.signedUrl});
 }
 return new Response("Invalid action",{status:400});
 }catch(_e){return Response.json({error:"Storage operation failed"},{status:400});}
});

