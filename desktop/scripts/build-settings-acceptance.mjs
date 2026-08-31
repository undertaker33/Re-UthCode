import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import webpack from "webpack";
const root=resolve(import.meta.dirname,".."); const output=resolve(root,"dist/ui-acceptance/prompt-2"); await mkdir(output,{recursive:true});
const compiler=webpack({mode:"development",target:"web",devtool:false,entry:resolve(root,"tests/render-settings-interactions-visual-fixture.tsx"),output:{path:output,filename:"fixture.js"},module:{rules:[{test:/\.tsx?$/u,exclude:/node_modules/u,use:{loader:"ts-loader",options:{configFile:resolve(root,"tsconfig.json"),transpileOnly:true} }},{test:/\.css$/u,type:"asset/source"}]},resolve:{extensions:[".js",".ts",".tsx"]}});
const stats=await new Promise((ok,bad)=>compiler.run((error,value)=>error?bad(error):ok(value))); compiler.close(()=>{}); if(stats.hasErrors())throw new Error(stats.toString({colors:false,errors:true,warnings:true}));
await writeFile(resolve(output,"index.html"),'<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prompt 2 Settings Acceptance</title></head><body><div id="root"></div><script src="fixture.js"></script></body></html>',"utf8");
process.stdout.write(`${stats.toString({colors:false,assets:true,modules:false})}\noutput=${output}\n`);
