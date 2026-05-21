// One-shot patch script: replace market.downstream.consumer with expanded version
const fs = require('fs');
const http = require('http');
const html = fs.readFileSync('D:/ai-native chrome/output/current.html', 'utf8');

let startPos = html.indexOf('data-anc="market.downstream.consumer"');
startPos = html.lastIndexOf('<', startPos);
let endPos = html.indexOf('data-anc="market.downstream.agents"');
endPos = html.lastIndexOf('<', endPos);

console.log('start=' + startPos + ' end=' + endPos + ' old_size=' + (endPos - startPos));

const newSection = [
'<section class="anc-section anc-element" data-anc="market.downstream.consumer" data-handles="refine,expand,branch,annotate">',
'  <h3>3.2 消费级 AI — 超级入口之争</h3>',
'  <p>消费级 AI 入口进入「超级应用」竞争阶段，呈现 <strong>通用助手平台</strong>（横向扩张）与 <strong>垂直行业入口</strong>（纵向渗透）两条主线并行格局。ChatGPT 月活突破 <strong>8.5 亿</strong>，Claude 月活 <strong>4.2 亿</strong>，AI 生成内容在社交媒体占比突破 <strong>22%</strong>。</p>',
'  <div class="anc-kpi-grid">',
'    <div class="anc-kpi anc-kpi--berry anc-kpi--center"><div class="kpi-value">8.5亿</div><div class="kpi-label">ChatGPT MAU</div></div>',
'    <div class="anc-kpi anc-kpi--ocean anc-kpi--center"><div class="kpi-value">4.2亿</div><div class="kpi-label">Claude MAU</div></div>',
'    <div class="anc-kpi anc-kpi--flame anc-kpi--center"><div class="kpi-value">22%</div><div class="kpi-label">AIGC 内容占比</div></div>',
'    <div class="anc-kpi anc-kpi--aurora anc-kpi--center"><div class="kpi-value">$142B</div><div class="kpi-label">C端AI市场规模</div></div>',
'  </div>',
'  <hr class="anc-divider">',
'  <section class="anc-section anc-element" data-anc="market.downstream.consumer.general" data-handles="refine,expand,annotate">',
'    <h4>■ 通用类 AI 入口</h4>',
'    <p>以跨场景、跨任务为核心，依托大模型构建统一对话界面，向搜索、创作、编程、助手方向扩张。</p>',
'    <table>',
'      <thead><tr><th>赛道</th><th>代表产品</th><th>月活规模</th><th>核心差异点</th><th>商业化路径</th></tr></thead>',
'      <tbody>',
'        <tr><td><strong>AI 搜索</strong></td><td>Perplexity、ChatGPT Search、Google AI Overviews、Kimi</td><td>Perplexity 1.5亿+/月</td><td>实时联网 + 引用溯源，替代传统 10 蓝链；Google 防御性嵌入</td><td>订阅 Pro ($20/月)、API 付费、广告竞价（实验中）</td></tr>',
'        <tr><td><strong>AI 助手 / 伴侣</strong></td><td>ChatGPT、Claude、Gemini、Microsoft Copilot、豆包、Kimi</td><td>ChatGPT 8.5亿、Claude 4.2亿、豆包 3亿+</td><td>模型能力差异化（推理/多模态/长文本）；记忆个性化；OS 级集成</td><td>Freemium + 订阅（$20-$200/月）；API 推理收费；企业版席位</td></tr>',
'        <tr><td><strong>AI 创作工具</strong></td><td>Midjourney、DALL-E 3、Sora、Runway Gen-3、ElevenLabs、Pika</td><td>Midjourney 2000万+付费用户</td><td>图像：写实度 vs 风格控制；视频：时长 vs 连贯性；音频：情感克隆</td><td>订阅制（$10-$96/月）；商业授权溢价；API 集成</td></tr>',
'        <tr><td><strong>AI 编程工具</strong></td><td>GitHub Copilot、Cursor、Windsurf、Replit AI、Claude Code</td><td>Copilot 180万付费用户</td><td>IDE 深度集成 vs 独立编辑器；Agentic 代码生成（Cursor Composer）</td><td>个人 $10-$20/月；企业 $39/席位/月；Token 消耗计费</td></tr>',
'      </tbody>',
'    </table>',
'    <div class="anc-pill-row">',
'      <span class="anc-pill anc-pill--active">搜索替代加速</span>',
'      <span class="anc-pill anc-pill--gen">助手 OS 级入口争夺</span>',
'      <span class="anc-pill anc-pill--review">编程工具渗透率 38% Dev</span>',
'    </div>',
'  </section>',
'  <hr class="anc-divider">',
'  <section class="anc-section anc-element" data-anc="market.downstream.consumer.vertical" data-handles="refine,expand,annotate">',
'    <h4>■ 垂直行业类 AI 入口</h4>',
'    <p>纵向深耕专业领域，以专有数据 + 领域专家知识构建壁垒，付费转化率显著高于通用赛道。</p>',
'    <div class="anc-kpi-grid">',
'      <div class="anc-kpi anc-kpi--cool"><div class="kpi-top"><div class="kpi-label-top">教育科技<br>EdTech AI</div><div class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg></div></div><div class="kpi-bottom"><div class="kpi-value">$18B</div><div class="kpi-unit">市场规模 +44%</div></div></div>',
'      <div class="anc-kpi anc-kpi--arctic"><div class="kpi-top"><div class="kpi-label-top">医疗健康<br>HealthAI</div><div class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg></div></div><div class="kpi-bottom"><div class="kpi-value">$22B</div><div class="kpi-unit">市场规模 +38%</div></div></div>',
'      <div class="anc-kpi anc-kpi--aurora"><div class="kpi-top"><div class="kpi-label-top">金融服务<br>FinAI</div><div class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg></div></div><div class="kpi-bottom"><div class="kpi-value">$31B</div><div class="kpi-unit">市场规模 +52%</div></div></div>',
'      <div class="anc-kpi anc-kpi--berry"><div class="kpi-top"><div class="kpi-label-top">内容娱乐<br>Entertainment</div><div class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg></div></div><div class="kpi-bottom"><div class="kpi-value">$28B</div><div class="kpi-unit">市场规模 +61%</div></div></div>',
'    </div>',
'    <table>',
'      <thead><tr><th>行业</th><th>代表产品</th><th>核心功能</th><th>付费转化</th><th>主要壁垒</th></tr></thead>',
'      <tbody>',
'        <tr><td><strong>教育科技</strong></td><td>Khan Academy Khanmigo、Duolingo Max、作业帮 AI、学而思 AI</td><td>AI 辅导、个性化学习路径、口语对练、作文批改</td><td>8-15%</td><td>课程版权、K12 合规、家长信任度</td></tr>',
'        <tr><td><strong>医疗健康</strong></td><td>Ada Health、Tempus、Spring Health、好大夫 AI、微医 AI</td><td>症状自查、用药建议、心理健康陪伴、影像辅诊</td><td>12-20%</td><td>HIPAA/医疗数据合规、责任归属</td></tr>',
'        <tr><td><strong>金融服务</strong></td><td>BloombergGPT、Morgan Stanley AI、蚂蚁金融 AI、度小满</td><td>智能投顾、风险评估、报告解读、信贷审核</td><td>15-25%</td><td>金融牌照、可解释性、SEC/银保监合规</td></tr>',
'        <tr><td><strong>法律合规</strong></td><td>Harvey、CoCounsel、iManage AI、法大大 AI</td><td>合同审查、案例检索、法规解读、诉状起草</td><td>20-35%</td><td>司法管辖差异、幻觉零容忍</td></tr>',
'        <tr><td><strong>内容娱乐</strong></td><td>Character.ai、Replika、NovelAI、抖音 AI 伴侣</td><td>AI 角色扮演、情感陪伴、AI 音乐生成、互动故事</td><td>5-12%（高 ARPU）</td><td>内容安全审核、版权归属、用户依赖管理</td></tr>',
'        <tr><td><strong>电商零售</strong></td><td>Amazon Rufus、Shopify Magic、淘宝问问、京东 AI 导购</td><td>AI 导购、个性化推荐、虚拟试穿、AI 客服</td><td>转化率提升 18-32%</td><td>实时库存联动、多模态商品理解</td></tr>',
'      </tbody>',
'    </table>',
'    <div class="anc-pill-row">',
'      <span class="anc-pill anc-pill--active">金融AI增速最快 +52%</span>',
'      <span class="anc-pill anc-pill--warn">医疗合规壁垒最高</span>',
'      <span class="anc-pill anc-pill--gen">娱乐ARPU提升 +61%</span>',
'      <span class="anc-pill anc-pill--done">法律付费转化最强 35%</span>',
'    </div>',
'  </section>',
'</section>',
].join('\n');

const newHtml = html.slice(0, startPos) + newSection + html.slice(endPos);
fs.writeFileSync('D:/ai-native chrome/output/current.html', newHtml, 'utf8');
console.log('File written: ' + newHtml.length + 'B (section: ' + newSection.length + 'B)');

// POST to /html to broadcast immediately (don't wait for file watcher)
const body = JSON.stringify({ html: newHtml });
const req = http.request({
  hostname: 'localhost', port: 3000, path: '/html', method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
}, res => {
  let d = ''; res.on('data', c => d += c);
  res.on('end', () => console.log('broadcast:', res.statusCode, d.slice(0, 100)));
});
req.on('error', e => console.error('POST error:', e.message));
req.write(body);
req.end();
