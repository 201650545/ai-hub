/* AI Hub 中央导航(:8000 /) · 皮肤切换器  localStorage: nav-skin */
(function(){
  const SKINS=[
    {id:'apple',   name:'苹果极简', icon:'🍎'},
    {id:'huawei',  name:'华为商务', icon:'🔵'},
    {id:'xiaomi',  name:'小米活力', icon:'🧡'},
    {id:'xiuxian', name:'修道仙侠', icon:'☯'},
    {id:'midnight',name:'科技暗夜', icon:'🌌'},
  ];
  const KEY='nav-skin';
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
    clearTimeout(_st);_st=setTimeout(()=>toast.classList.remove('show'),1600);
  }
  function apply(id,quiet){
    document.documentElement.setAttribute('data-skin',id);
    try{localStorage.setItem(KEY,id);}catch(e){}
    menu.querySelectorAll('.skin-chip').forEach(c=>c.classList.toggle('on',c.dataset.skin===id));
    fab.textContent=id==='xiuxian'?'☯':'🎨';
    if(!quiet){const s=SKINS.find(x=>x.id===id);showToast((s?s.icon+' ':'')+'已切换：'+(s?s.name:id));}
  }
  menu.addEventListener('click',e=>{
    const c=e.target.closest('.skin-chip');if(c)apply(c.dataset.skin);
  });
  let cur='apple';
  try{cur=localStorage.getItem(KEY)||'apple';}catch(e){}
  apply(cur,true);
})();
