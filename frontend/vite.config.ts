import { defineConfig, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

const localProxy = ():ProxyOptions => ({
  target:'http://127.0.0.1:8000',
  changeOrigin:false,
  configure(proxy){
    const events=proxy as unknown as {on(event:'proxyReq',listener:(request:{setHeader(name:string,value:string):void},incoming:{headers:{host?:string}})=>void):void};
    events.on('proxyReq',(proxyReq,req)=>{
      if(req.headers.host)proxyReq.setHeader('host',req.headers.host);
    });
  },
});

export default defineConfig({plugins:[react()],server:{port:5173,proxy:{'/api':localProxy(),'/health':localProxy()}}});
