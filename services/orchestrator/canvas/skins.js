/* =====================================================================
   :8791 皮肤切换器（index.html 与 gallery.html 共用）
   localStorage: orch-skin · 默认 apple（保持现状）
   ===================================================================== */
(function(){
  const SKINS=[
    {id:'apple',   name:'苹果极简', icon:'🍎'},
    {id:'midnight',name:'科技暗夜', icon:'🌌'},
    {id:'xiuxian', name:'修道仙侠', icon:'☯'},
  ];
  const KEY='orch-skin';
  const DAOS=[
    '顺为凡，逆则仙，只在心中一念间。',
    '修的是道，行的是心。',
    '不惧万骨枯，只求本心明。',
    '大道三千，取其一而行之。',
    '心如磐石，道途自远。',
    '一念起，万水千山；一念灭，沧海桑田。',
    '踏碎凌霄，放肆桀骜又何妨。',
    '修行如逆水行舟，不进则退。',
    '天地为炉，造化为工。',
    '道可道，非常道；名可名，非常名。',
    '斩尽荆棘，方见通天之路。',
    '今日之果，皆昨日之因。',
  ];

  const dock=document.createElement('div');
  dock.id='skin-dock';
  dock.innerHTML='<div id="skin-menu"></div><button id="skin-fab" title="切换界面风格">🎨</button>';
  document.body.appendChild(dock);
  const toast=document.createElement('div');
  toast.id='skin-toast';
  document.body.appendChild(toast);

  const menu=dock.querySelector('#skin-menu'), fab=dock.querySelector('#skin-fab');
  menu.innerHTML=SKINS.map(s=>
    '<button class="skin-chip" data-skin="'+s.id+'">'+s.icon+' '+s.name+'</button>'
  ).join('');
  fab.addEventListener('click',()=>menu.classList.toggle('open'));
  document.addEventListener('click',e=>{
    if(!dock.contains(e.target))menu.classList.remove('open');
  });

  let _st=null;
  function showToast(msg){
    toast.textContent=msg;toast.classList.add('show');
    clearTimeout(_st);_st=setTimeout(()=>toast.classList.remove('show'),1800);
  }

  function apply(id,quiet){
    document.documentElement.setAttribute('data-skin',id);
    try{localStorage.setItem(KEY,id);}catch(e){}
    menu.querySelectorAll('.skin-chip').forEach(c=>c.classList.toggle('on',c.dataset.skin===id));
    fab.textContent=id==='kawaii'?'🎀':(id==='xiuxian'?'☯':'🎨');
    if(!quiet){
      const s=SKINS.find(x=>x.id===id);
      let msg=(s?s.icon+' ':'')+'已切换：'+(s?s.name:id);
      if(id==='xiuxian')msg+='\n'+DAOS[Math.floor(Math.random()*DAOS.length)];
      showToast(msg);
    }
  }
  menu.addEventListener('click',e=>{
    const c=e.target.closest('.skin-chip');
    if(c)apply(c.dataset.skin);
  });

  let cur='apple';
  try{cur=localStorage.getItem(KEY)||'apple';}catch(e){}
  apply(cur,true);
})();
