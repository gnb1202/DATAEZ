// Real-time full browser playback of all three exports, not a seek-only check.
const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1080}});
 const results=await Promise.all(['product','technical','loop'].map(async name=>{
  const page=await context.newPage();await page.goto('http://127.0.0.1:3134/');
  const result=await page.evaluate(async name=>{
   const video=document.getElementById('video-'+name);video.loop=false;video.muted=true;video.playbackRate=1;
   const samples=[];let stalls=0;video.addEventListener('stalled',()=>stalls++);
   const timer=setInterval(()=>samples.push({time:video.currentTime,ready:video.readyState}),1000);
   const start=performance.now();
   const ended=new Promise((resolve,reject)=>{video.addEventListener('ended',resolve,{once:true});video.addEventListener('error',()=>reject(new Error('Media error '+video.error?.code)),{once:true});});
   await video.play();await ended;clearInterval(timer);
   const quality=video.getVideoPlaybackQuality();
   return {name,ended:video.ended,duration:video.duration,current_time:video.currentTime,wall_seconds:(performance.now()-start)/1000,
    width:video.videoWidth,height:video.videoHeight,stalls,total_frames:quality.totalVideoFrames,dropped_frames:quality.droppedVideoFrames,samples};
  },name);
  await page.close();console.log('Playback ended: '+name);return result;
 }));
 await fs.writeFile('docs/portfolio-demo/phase-3-playback.json',JSON.stringify({passed:results.every(r=>r.ended&&r.width===1920&&r.height===1080),rate:1,results},null,2)+'\n');
 await browser.close();
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
