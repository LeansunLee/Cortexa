let configData = { default: "", providers: {} };

async function loadConfig() {
  const res = await fetch("/api/config");
  configData = await res.json();
  renderProviders();
  renderDefaultSelect();
}

function renderDefaultSelect() {
  const sel = document.getElementById("default-select");
  const badge = document.getElementById("default-badge");
  sel.innerHTML = "";
  for (const name of Object.keys(configData.providers)) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === configData.default) opt.selected = true;
    sel.appendChild(opt);
  }
  badge.textContent = configData.default || "未设置";
}

function renderProviders() {
  const list = document.getElementById("provider-list");
  list.innerHTML = "";
  for (const [name, prov] of Object.entries(configData.providers)) {
    const isActive = name === configData.default;
    const keyOk = prov.api_key_set;
    list.innerHTML += `
      <div class="provider-item ${isActive ? "active" : ""}" onclick="editProvider('${name}')">
        <div style="flex:1">
          <div class="name">${name}</div>
          <div class="meta">${prov.model} ${prov.base_url ? "· " + prov.base_url : ""}</div>
        </div>
        <span class="badge badge-kind">${prov.kind}</span>
        <span class="badge ${keyOk ? "badge-key-ok" : "badge-key-missing"}">${keyOk ? "✓ Key 已配置" : "✗ Key 缺失"}</span>
        ${isActive ? '<span class="badge badge-active">默认</span>' : ""}
        <div class="provider-actions">
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();deleteProvider('${name}')">删除</button>
        </div>
      </div>`;
  }
}

async function saveDefault() {
  const val = document.getElementById("default-select").value;
  await fetch("/api/config/default", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ default: val }),
  });
  configData.default = val;
  renderProviders();
  renderDefaultSelect();
  toast("已切换默认供应商: " + val, "success");
}

function openAddModal() {
  document.getElementById("modal-title").textContent = "添加供应商";
  document.getElementById("edit-name").value = "";
  document.getElementById("f-name").value = "";
  document.getElementById("f-name").disabled = false;
  document.getElementById("f-kind").value = "openai";
  document.getElementById("f-model").value = "";
  document.getElementById("f-base-url").value = "";
  document.getElementById("f-api-key").value = "";
  document.getElementById("f-temp").value = "0.2";
  document.getElementById("f-max-tokens").value = "4096";
  showModal();
}

function editProvider(name) {
  const prov = configData.providers[name];
  document.getElementById("modal-title").textContent = "编辑供应商: " + name;
  document.getElementById("edit-name").value = name;
  document.getElementById("f-name").value = name;
  document.getElementById("f-name").disabled = true;
  document.getElementById("f-kind").value = prov.kind;
  document.getElementById("f-model").value = prov.model;
  document.getElementById("f-base-url").value = prov.base_url;
  document.getElementById("f-api-key").value = "";
  document.getElementById("f-api-key").placeholder = prov.api_key_set ? "已配置（留空不修改）" : "未配置";
  document.getElementById("f-temp").value = prov.temperature;
  document.getElementById("f-max-tokens").value = prov.max_tokens;
  showModal();
}

async function saveProvider(e) {
  e.preventDefault();
  const data = {
    name: document.getElementById("f-name").value.trim(),
    kind: document.getElementById("f-kind").value,
    model: document.getElementById("f-model").value.trim(),
    base_url: document.getElementById("f-base-url").value.trim(),
    api_key: document.getElementById("f-api-key").value,
    temperature: parseFloat(document.getElementById("f-temp").value),
    max_tokens: parseInt(document.getElementById("f-max-tokens").value),
  };
  await fetch("/api/config/provider", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  closeModal();
  await loadConfig();
  toast("供应商已保存: " + data.name, "success");
}

async function deleteProvider(name) {
  if (!confirm("确定删除供应商 " + name + " ?")) return;
  await fetch("/api/config/provider/" + name, { method: "DELETE" });
  await loadConfig();
  toast("已删除: " + name, "success");
}

function showModal() {
  const el = document.getElementById("modal-overlay");
  el.style.display = "flex";
}
function closeModal() {
  document.getElementById("modal-overlay").style.display = "none";
}

function toast(msg, type = "success") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast toast-" + type;
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 2500);
}

loadConfig();
