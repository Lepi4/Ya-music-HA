// hass.callApi already prefixes /api/.
const API = "yandex_music_chaos/v1";
const PANEL_VERSION = "0.3.2";

class YandexMusicChaosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
  }

  querySelector(selector) { return this.shadowRoot.querySelector(selector); }
  querySelectorAll(selector) { return this.shadowRoot.querySelectorAll(selector); }
  set hass(value) {
    this._hass = value;
    if (this._mounted && this.isConnected) {
      this.syncPlayerStates();
      if (!this._initialized) this.loadInitial();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (this._mounted) {
      window.addEventListener("pointerup", this._releaseStation);
      window.addEventListener("pointercancel", this._releaseStation);
      this.startLayout();
      this.startPolling();
      this.refreshPlayers();
      return;
    }
    this._mounted = true;
    this._section = "home";
    this._tracks = [];
    this._queue = [];
    this._index = -1;
    this._targets = [];
    this._volumeTarget = "";
    this._players = [];
    this._selectedPlayerId = "";
    this._stationQueues = new Map();
    this._radioSessions = {};
    this._stationTargets = new Map();
    this._catalogCache = new Map();
    this._sourceInfo = new Map();
    this._inputSourceBusy = false;
    this._title = "Яндекс Музыка";
    this.shadowRoot.innerHTML = `<style>${CSS}</style><div class="ym-shell">
  <aside class="ym-sidebar" aria-label="Библиотека">
    <div class="ym-brand"><span class="ym-brand-mark">♫</span><span>Яндекс Музыка<small class="ym-version">${PANEL_VERSION}</small></span></div>
    <div class="ym-nav-caption">Обзор</div>
    <button class="ym-nav active" data-section="home"><span>◈</span>Главная</button>
    <button class="ym-nav" data-section="search"><span>⌕</span>Поиск</button>
    <div class="ym-nav-caption">Медиатека</div>
    <button class="ym-nav" data-section="playlists"><span>☷</span>Плейлисты</button>
    <button class="ym-nav" data-section="likes"><span>♡</span>Мне нравится</button>
    <button class="ym-nav" data-section="wave"><span>◉</span>Моя волна</button>
    <button class="ym-nav" data-section="chart"><span>↗</span>Чарт</button>
    <button class="ym-nav" data-section="podcasts"><span>♬</span>Подкасты</button>
    <button class="ym-nav" data-section="audiobooks"><span>▤</span>Аудиокниги</button>
    <div id="ym-account" class="ym-account">Подключение…</div>
  </aside>
  <div class="ym-workspace">
    <section class="ym-player-area" aria-label="Плеер и Яндекс-колонки">
      <div class="ym-stations-heading"><h2>Яндекс-колонки</h2><span>Выберите, чем управлять</span></div>
      <div id="ym-stations" class="ym-stations" aria-label="Выбор колонки"></div>
      <button class="ym-input-source-button" data-action="input-source" aria-haspopup="dialog"><span class="ym-input-source-icon">⇄</span><span><small>Источник воспроизведения</small><strong id="ym-input-source-name">Загрузка…</strong></span><span class="ym-input-source-change">Сменить источник ▾</span></button>
      <section class="ym-player" aria-label="Управление выбранной колонкой">
        <div class="ym-now"><div class="ym-artwork"><span>♫</span><img id="ym-cover" alt="" hidden></div><div class="ym-now-copy"><span id="ym-player-name" class="ym-player-name">Выберите колонку</span><strong id="ym-now-title">Ничего не играет</strong><span id="ym-now-artist" class="ym-muted">Выберите музыку в библиотеке</span></div></div>
        <div class="ym-transport"><div class="ym-controls"><button data-cmd="previous" aria-label="Предыдущий трек">⏮</button><button class="ym-play" data-cmd="toggle" aria-label="Воспроизвести">▶</button><button data-cmd="next" aria-label="Следующий трек">⏭</button><button data-cmd="stop" aria-label="Остановить">■</button></div><div class="ym-timeline"><span id="ym-position">0:00</span><input id="ym-seek" type="range" min="0" max="1" value="0" step="1" aria-label="Позиция трека" disabled><span id="ym-duration">0:00</span></div></div>
        <div class="ym-player-actions"><button class="ym-action" data-action="sources" aria-haspopup="dialog">▣ <span>Куда воспроизводить<small id="ym-target-label">Выберите колонку</small></span></button><button class="ym-icon-button" data-action="queue" aria-label="Открыть очередь" title="Очередь">☷</button><button class="ym-icon-button" data-action="track-wave" aria-label="Волна по текущему треку" title="Волна по текущему треку">◉</button></div>
        <div class="ym-volume"><button class="ym-icon-button" data-cmd="mute" aria-label="Выключить звук">♪</button><input id="ym-volume" type="range" min="0" max="1" step="0.01" value="0" aria-label="Громкость выбранной колонки" disabled><output id="ym-volume-value">—</output></div>
        <p id="ym-radio-status" class="ym-radio-status" role="status" hidden></p>
      </section>
    </section>
    <main class="ym-main"><header class="ym-header"><h1 id="ym-heading">Главная</h1><div class="ym-search"><span>⌕</span><input id="ym-search" type="search" placeholder="Трек, исполнитель, альбом…" aria-label="Поиск в Яндекс Музыке"><button data-action="search" aria-label="Найти">Найти</button></div></header><div id="ym-error" class="ym-error hidden" role="alert"></div><div id="ym-notice" class="ym-notice hidden" role="status"></div><section id="ym-content" aria-live="polite"></section></main>
  </div>
</div>
<dialog id="ym-sources-dialog" class="ym-dialog" aria-labelledby="ym-sources-title"><div class="ym-dialog-head"><h2 id="ym-sources-title">Куда воспроизводить</h2><button class="ym-icon-button" data-action="close-dialog" aria-label="Закрыть">×</button></div><p class="ym-muted">Выберите одну или несколько Яндекс-колонок.</p><div id="ym-source-options"></div><p id="ym-sources-error" class="ym-inline-error" role="alert"></p><div class="ym-dialog-buttons"><button class="ym-secondary" data-action="apply-sources">Выбрать для новой музыки</button><button class="ym-primary" data-action="send-current">Отправить текущий трек</button></div></dialog>
<dialog id="ym-queue-dialog" class="ym-dialog" aria-labelledby="ym-queue-title"><div class="ym-dialog-head"><h2 id="ym-queue-title">Очередь</h2><button class="ym-icon-button" data-action="close-dialog" aria-label="Закрыть">×</button></div><div id="ym-queue-content"></div></dialog>
<dialog id="ym-input-source-dialog" class="ym-dialog" aria-labelledby="ym-input-source-title"><div class="ym-dialog-head"><h2 id="ym-input-source-title">Источник воспроизведения</h2><button class="ym-icon-button" data-action="close-dialog" aria-label="Закрыть">×</button></div><p id="ym-input-source-station" class="ym-muted"></p><div id="ym-input-source-options"></div><p id="ym-input-source-error" class="ym-inline-error" role="alert"></p></dialog>
`;
    this.shadowRoot.addEventListener("click", (event) => this.onClick(event));
    this.shadowRoot.addEventListener("pointerdown", event => {
      if (event.target.closest("[data-station]")) this._stationPointer = event.pointerId;
    });
    const releaseStation = event => {
      if (this._stationPointer !== event.pointerId) return;
      // Let the click land before a state update can reorder the cards.
      setTimeout(() => { this._stationPointer = null; if (this.isConnected) this.renderOutputs(); }, 0);
    };
    this.shadowRoot.addEventListener("pointerup", releaseStation);
    this.shadowRoot.addEventListener("pointercancel", releaseStation);
    this.shadowRoot.addEventListener("lostpointercapture", releaseStation);
    this._releaseStation = releaseStation;
    window.addEventListener("pointerup", releaseStation);
    window.addEventListener("pointercancel", releaseStation);
    this.shadowRoot.addEventListener("change", (event) => this.onChange(event));
    this.querySelector("#ym-search").addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.search();
    });
    this.querySelector("#ym-search").addEventListener("input", () => {
      if (this._section !== "search") this.filterSection(this.querySelector("#ym-search").value);
    });
    this.querySelector(".ym-sidebar").addEventListener("wheel", event => {
      if (event.ctrlKey || event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      const workspace = this.querySelector(".ym-workspace");
      if (workspace.scrollHeight > workspace.clientHeight) {
        event.preventDefault();
        workspace.scrollBy({top:event.deltaY, behavior:"instant"});
      }
    }, {passive:false});
    this.querySelector("#ym-volume").addEventListener("input", event => {
      this.querySelector("#ym-volume-value").textContent = `${Math.round(Number(event.target.value)*100)}%`;
    });
    this.startPolling();
    this.startLayout();
    this.loadInitial();
  }

  startLayout() {
    if (this._layoutHandler) return;
    this._layoutHandler = () => {
      const top = Math.max(0, this.getBoundingClientRect().top);
      this.style.setProperty("--ym-panel-height", `${Math.max(100, innerHeight-top)}px`);
    };
    window.addEventListener("resize", this._layoutHandler);
    this._layoutObserver = new ResizeObserver(this._layoutHandler);
    if (this.parentElement) this._layoutObserver.observe(this.parentElement);
    this._layoutFrame = requestAnimationFrame(this._layoutHandler);
  }

  startPolling() {
    if (!this._pollTimer) this._pollTimer = setInterval(() => { if (!document.hidden) this.refreshPlayers(); }, 5000);
  }

  syncPlayerStates() {
    this._players = (this._players || []).map((player) => {
      const state = this.hass?.states?.[player.entity_id];
      if (!state) return {...player, ...this._sourceInfo.get(player.entity_id)};
      const a = state.attributes;
      return {...player, state: state.state, title: a.media_title,
        artist: a.media_artist || a.media_artist_name, image: a.entity_picture || a.media_image_url,
        volume: a.volume_level, muted: a.is_volume_muted, position: a.media_position,
        duration: a.media_duration, media_id: a.media_content_id,
        input_source: a.source, source_list: a.source_list || []};
    });
    this.updateNowPlaying();
    this.renderOutputs();
  }

  disconnectedCallback() {
    window.removeEventListener("pointerup", this._releaseStation);
    window.removeEventListener("pointercancel", this._releaseStation);
    this._stationPointer = null;
    clearInterval(this._pollTimer);
    this._pollTimer = null;
    clearTimeout(this._noticeTimer);
    this.querySelectorAll("dialog").forEach(dialog => dialog.close());
    window.removeEventListener("resize", this._layoutHandler);
    this._layoutObserver?.disconnect();
    cancelAnimationFrame(this._layoutFrame);
    this._layoutHandler = null;
  }

  async api(path, options = {}) {
    if (!this.hass?.callApi) throw new Error("Home Assistant ещё не передал API");
    return this.hass.callApi(options.method || "GET", `${API}${path}`, options.body);
  }

  async loadInitial() {
    if (!this.hass?.callApi || this._initializing) return;
    this._initializing = true;
    try {
      const status = await this.api("/status");
      this._players = status.players || [];
      this._radioSessions = status.playback?.radio || {};
      let saved;
      try { saved = localStorage.getItem("ym-chaos.active-player"); } catch (_) {}
      const stations = this.stations();
      const initial = stations.find(p => p.entity_id === saved && !["unavailable", "unknown"].includes(p.state))
        || stations.find(p => ["playing", "buffering"].includes(p.state))
        || stations.find(p => p.source && !["unavailable", "unknown"].includes(p.state))
        || stations.find(p => !["unavailable", "unknown"].includes(p.state));
      this.selectStation(initial?.entity_id || "");
      this._initialized = true;
      this.setAccount(status.account);
      this.updateNowPlaying();
      this.renderTargets();
      this.renderOutputs();
      if (status.error) this.showError(status.error);
      else await this.loadSection("home");
    } catch (error) {
      this.showError(error);
    } finally {
      this._initializing = false;
    }
  }

  async refreshPlayers() {
    if (!this.hass?.callApi || !this._initialized || this._refreshing) return;
    this._refreshing = true;
    const radioRevision = this._radioRevision;
    try {
      const data = await this.api("/players");
      this._players = data.players || [];
      if (radioRevision === this._radioRevision) this._radioSessions = data.playback?.radio || {};
      this.syncPlayerStates();
      this.updateNowPlaying();
      this.renderTargets();
      this.renderOutputs();
    } catch (error) {
      this.showError(error);
    } finally { this._refreshing = false; }
  }

  setAccount(account) {
    const label = account?.login ? `${account.login}${account.plus ? " · Plus" : ""}` : "Не удалось подключить аккаунт";
    this.querySelector("#ym-account").textContent = label;
  }

  showError(error) {
    const box = this.querySelector("#ym-error");
    if (!box) return;
    const detail = typeof error === "string"
      ? error
      : (error?.body?.error || error?.message || error?.error || (() => { try { return JSON.stringify(error); } catch (_) { return String(error); } })());
    box.textContent = detail || "Ошибка запроса к Home Assistant";
    box.classList.remove("hidden");
  }

  clearError() {
    this.querySelector("#ym-error")?.classList.add("hidden");
  }

  async catalog(path) {
    const cached = this._catalogCache.get(path);
    if (cached && Date.now()-cached.time < 300000) return cached.value;
    const value = await this.api(path);
    this._catalogCache.set(path, {time:Date.now(), value});
    return value;
  }

  async loadSection(section, extra = {}) {
    const revision = this._sectionRevision = (this._sectionRevision || 0)+1;
    this._section = section;
    this._tracks = [];
    this._sectionData = null;
    this._sectionTitle = "";
    this._trackMap = {};
    this.clearError();
    this.querySelectorAll(".ym-nav").forEach(node => node.classList.toggle("active", node.dataset.section === section));
    const content = this.querySelector("#ym-content");
    content.innerHTML = '<div class="ym-loading">Загрузка…</div>';
    this.querySelector(".ym-workspace").scrollTop = 0;
    const search = this.querySelector("#ym-search");
    search.value = extra.query || "";
    search.placeholder = section === "search" ? "По всей Яндекс Музыке…" : section === "home" ? "В подборках на этой странице…" : "Найти в этом разделе…";
    search.setAttribute("aria-label", section === "search" ? "Глобальный поиск в Яндекс Музыке" : "Поиск внутри текущего раздела");
    const titles = {home:"Главная",playlists:"Плейлисты",likes:"Мне нравится",wave:"Моя волна",chart:"Чарт",podcasts:"Подкасты",audiobooks:"Аудиокниги",search:extra.query ? `Поиск: ${extra.query}` : "Поиск"};
    this.querySelector("#ym-heading").textContent = titles[section] || "Загрузка…";
    if (section === "search" && !extra.query) {
      content.innerHTML = '<div class="ym-search-welcome"><span>⌕</span><h2>Поиск в Яндекс Музыке</h2><p>Найдите трек, исполнителя, альбом, плейлист, сказку или подкаст во всём каталоге.</p><div class="ym-search-suggestions"><button data-search-query="Сказки">Найти сказки</button><button data-search-query="Аудиокниги">Найти аудиокниги</button><button data-section="podcasts">Каталог подкастов</button></div></div>';
      search.focus();
      return;
    }
    if (section === "home") {
      content.innerHTML = '<div class="ym-wave-banner"><div><h2>Моя волна</h2><p>Музыка под ваш вкус — от Яндекс Музыки</p></div><button class="ym-primary" data-action="start-wave">▶ Слушать</button></div><div id="ym-recommendations"><div class="ym-loading">Загружаем подборки Яндекс Музыки…</div></div><div id="ym-home-playlists"></div><div id="ym-home-likes"></div>';
      const renderError = (error, target) => {
        if (revision !== this._sectionRevision) return;
        this.querySelector(target).innerHTML = '<p class="ym-muted">Не удалось загрузить раздел.</p>';
        this.showError(error);
      };
      await Promise.allSettled([
        this.catalog("/recommendations").then(data => { if (revision === this._sectionRevision) this.querySelector("#ym-recommendations").innerHTML = (data.shelves || []).map(shelf => this.shelf(shelf.title, shelf.items)).join(""); }).catch(error => renderError(error,"#ym-recommendations")),
        this.catalog("/playlists").then(data => { if (revision === this._sectionRevision) this.querySelector("#ym-home-playlists").innerHTML = this.shelf("Ваши плейлисты", data.playlists || []); }).catch(error => renderError(error,"#ym-home-playlists")),
        this.catalog("/likes").then(data => { if (revision === this._sectionRevision) this.querySelector("#ym-home-likes").innerHTML = '<div class="ym-section-head"><h2>Мне нравится</h2><button class="ym-link" data-section="likes">Все треки →</button></div>'+this.trackRows((data.tracks || []).slice(0,6)); }).catch(error => renderError(error,"#ym-home-likes"))
      ]);
      if (revision === this._sectionRevision) this.filterSection(search.value);
      return;
    }
    try {
      let path = {playlists:"/playlists", likes:"/likes", wave:"/wave", chart:"/chart",podcasts:"/podcasts"}[section];
      if (section === "playlist") path = `/playlists/${encodeURIComponent(extra.uid)}/${encodeURIComponent(extra.kind)}`;
      if (section === "album") path = `/albums/${encodeURIComponent(extra.id)}`;
      if (section === "search") path = `/search?q=${encodeURIComponent(extra.query || "")}`;
      if (section === "audiobooks") path = `/audiobooks?q=${encodeURIComponent(extra.query || "")}`;
      const data = await (section === "wave" ? this.api(path) : this.catalog(path));
      if (revision !== this._sectionRevision) return;
      if (extra.title || data.title) this.querySelector("#ym-heading").textContent = extra.title || data.title;
      this._sectionData = data;
      this._sectionTitle = this.querySelector("#ym-heading").textContent;
      if (section === "wave") {
        this._tracks = data.tracks || [];
        content.innerHTML = '<div class="ym-wave-banner"><div><h2>Бесконечная волна</h2><p>Отдельный поток на выбранной колонке. Следующие треки подгружает Home Assistant.</p></div><button class="ym-primary" data-action="start-wave">▶ Слушать</button></div><div class="ym-wave-settings"><label for="ym-wave-mood">Настроение</label><select id="ym-wave-mood" disabled><option value="">Загрузка…</option></select><button class="ym-secondary" data-action="mood-wave" disabled>Применить и слушать</button><p class="ym-muted">Настроение сохраняется в музыкальном аккаунте и может влиять на его волну на других устройствах.</p><p id="ym-wave-settings-error" class="ym-muted"></p></div><div class="ym-section-head"><h2>Фрагмент рекомендаций</h2></div><p class="ym-muted">Это первый пакет API, а не полная очередь потока. Для непрерывного воспроизведения нажмите «Слушать».</p>'+this.trackRows(this._tracks);
        this.loadWaveSettings(revision);
      } else if (section === "audiobooks") {
        this._bookQuery = extra.query || "";
        this.renderBooks(data);
      } else if (section === "playlists" || section === "podcasts") content.innerHTML = `<div class="ym-card-grid">${(data.playlists || data.items || []).map(item => this.card(item)).join("")}</div>`;
      else if (section === "search") {
        this._tracks = [...(data.tracks || []), ...(data.podcast_episodes || [])];
        content.innerHTML = (data.tracks?.length ? this.trackRows(data.tracks) : "") + this.shelf("Плейлисты", data.playlists || []) + this.shelf("Альбомы", (data.albums || []).map(item => ({...item,type:"album"}))) + this.shelf("Подкасты", data.podcasts || []) + (data.podcast_episodes?.length ? '<div class="ym-section-head"><h2>Выпуски подкастов</h2></div>'+this.trackRows(data.podcast_episodes) : "");
        if (!content.innerHTML) content.innerHTML = '<p class="ym-empty">Ничего не найдено.</p>';
      } else {
        this._tracks = data.tracks || [];
        content.innerHTML = `<div class="ym-list-toolbar"><span>${this._tracks.length} треков</span><button class="ym-primary" data-action="play-all" ${this._tracks.length ? "" : "disabled"}>▶ Воспроизвести</button></div>${this.trackRows(this._tracks)}`;
      }
      if (section !== "search") this.filterSection(search.value);
    } catch (error) { if (revision === this._sectionRevision) { content.innerHTML = ""; this.showError(error); } }
  }

  filterSection(query) {
    if (this._section === "search") return;
    const words = String(query || "").toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    const matches = item => {
      const text = [item.title,item.artists,item.artist,item.album].filter(Boolean).join(" ").toLocaleLowerCase();
      return words.every(word => text.includes(word));
    };
    const content = this.querySelector("#ym-content");
    if (this._sectionData) {
      if (this._section === "audiobooks") {
        this.renderBooks({...this._sectionData, shelves:(this._sectionData.shelves || []).map(shelf => ({...shelf, items:shelf.items.filter(matches)}))});
      } else if (this._section === "wave") {
        content.querySelectorAll(".ym-track").forEach(node => {
          const text = node.textContent.toLocaleLowerCase();
          node.hidden = !words.every(word => text.includes(word));
        });
      } else if (this._section === "playlists" || this._section === "podcasts") {
        const items = (this._sectionData.playlists || this._sectionData.items || []).filter(matches);
        content.innerHTML = items.length ? `<div class="ym-card-grid">${items.map(item => this.card(item)).join("")}</div>` : '<p class="ym-empty">В этом разделе ничего не найдено.</p>';
      } else {
        this._tracks = (this._sectionData.tracks || []).filter(matches);
        content.innerHTML = `<div class="ym-list-toolbar"><span>${this._tracks.length} треков</span><button class="ym-primary" data-action="play-all" ${this._tracks.length ? "" : "disabled"}>▶ Воспроизвести</button></div>${this.trackRows(this._tracks)}`;
      }
    } else if (this._section === "home") {
      // Home contains heterogeneous API shelves: filter rendered card/track text.
      content.querySelectorAll(".ym-card,.ym-track").forEach(node => {
        const text = node.textContent.toLocaleLowerCase();
        node.hidden = !words.every(word => text.includes(word));
      });
      content.querySelectorAll(".ym-shelf").forEach(shelf => { shelf.hidden = !shelf.querySelector(".ym-card:not([hidden])"); });
      const wave = content.querySelector(".ym-wave-banner");
      if (wave) wave.hidden = !!words.length;
    }
  }

  renderBooks(data) {
    this.querySelector("#ym-content").innerHTML = '<p class="ym-muted">Аудиокниги из каталога Яндекс Музыки. Поиск — по названию или автору; Enter ищет книги в каталоге.</p>' + (data.shelves || []).map(shelf => this.shelf(shelf.title, shelf.items)).join("") + ((data.shelves || []).some(shelf => shelf.items.length) ? "" : '<p class="ym-empty">Книг на этой странице не найдено.</p>') + (data.next_page !== null && data.next_page !== undefined ? '<button class="ym-secondary" data-action="more-books">Загрузить ещё</button>' : "");
  }

  async moreBooks() {
    const revision = this._sectionRevision;
    const data = this._sectionData;
    const button = this.querySelector('[data-action="more-books"]');
    if (!data || data.next_page == null || !button || button.disabled) return;
    button.disabled = true;
    try {
      const next = await this.api(`/audiobooks?q=${encodeURIComponent(this._bookQuery || "")}&page=${data.next_page}`);
      if (revision !== this._sectionRevision) return;
      const current = data.shelves.find(shelf => shelf.id === "catalog");
      const ids = new Set(current.items.map(item => item.id));
      for (const item of next.shelves.find(shelf => shelf.id === "catalog")?.items || []) if (!ids.has(item.id)) { current.items.push(item); ids.add(item.id); }
      data.next_page = next.next_page;
      this.filterSection(this.querySelector("#ym-search").value);
    } catch (error) { if (revision === this._sectionRevision) this.showError(error); }
    finally { if (button.isConnected) button.disabled = false; }
  }

  shelf(title, items) {
    return items.length ? `<section class="ym-shelf"><div class="ym-section-head"><h2>${escapeHtml(title)}</h2></div><div class="ym-card-row">${items.map(item => this.card(item)).join("")}</div></section>` : "";
  }

  card(item) {
    const data = item.type === "album" ? `data-album="${escapeHtml(item.id)}"` : `data-playlist-uid="${escapeHtml(item.uid)}" data-playlist-kind="${escapeHtml(item.kind)}"`;
    return `<button class="ym-card" ${data} data-title="${escapeHtml(item.title)}"><div class="ym-card-art">${item.cover ? `<img src="${escapeHtml(item.cover)}" alt="" loading="lazy" decoding="async">` : "♫"}<span class="ym-card-play">▶</span></div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.artist || (item.type === "album" ? "Альбом" : `${item.count || 0} треков`))}</small></button>`;
  }

  trackRows(tracks) {
    if (!tracks.length) return '<p class="ym-empty">Здесь пока ничего нет.</p>';
    tracks.forEach(track => { this._trackMap[track.id] = track; });
    return `<div class="ym-tracks">${tracks.map((track,index) => `<button class="ym-track" data-track-id="${escapeHtml(track.id)}"><span class="ym-track-number">${index+1}</span><div class="ym-track-art">${track.cover ? `<img src="${escapeHtml(track.cover)}" alt="" loading="lazy" decoding="async">` : "♫"}</div><span class="ym-track-main"><strong>${escapeHtml(track.title || "Без названия")}</strong><small>${escapeHtml(track.artists || "")}</small></span><span class="ym-track-time">${formatTime(track.duration)}</span><span class="ym-track-play">▶</span></button>`).join("")}</div>`;
  }

  stations() {
    return this._players.filter(p => p.is_yandex_station || p.entity_id.startsWith("media_player.yandex_station_") || p.source);
  }

  activePlayer() { return this.stations().find(p => p.entity_id === this._selectedPlayerId); }

  selectStation(id) {
    const player = this.stations().find(p => p.entity_id === id);
    if (!player || ["unavailable", "unknown"].includes(player.state)) return;
    this._selectedPlayerId = id;
    this._targets = this._stationTargets.get(id) || [id];
    try { localStorage.setItem("ym-chaos.active-player", id); } catch (_) {}
    this.updateNowPlaying();
    this.renderOutputs();
    this.hydrateSource(id).catch(error => this.showError(error));
  }

  renderTargets() {} // Devices belong to the player picker, never the library navigation.

  renderOutputs() {
    const box = this.querySelector("#ym-stations");
    if (!box) return;
    const playing = p => ["playing", "buffering"].includes(p.state);
    const stations = [...this.stations()].sort((a,b) => Number(playing(b))-Number(playing(a)) || a.name.localeCompare(b.name));
    if (!stations.length) {
      if (!box.querySelector(".ym-muted")) box.innerHTML = '<p class="ym-muted">Нет доступных Яндекс-колонок.</p>';
      return;
    }
    box.querySelector(".ym-muted")?.remove();
    const buttons = new Map([...box.querySelectorAll("[data-station]")].map(button => [button.dataset.station, button]));
    for (const p of stations) {
      let button = buttons.get(p.entity_id);
      if (!button) {
        button = document.createElement("button");
        button.dataset.station = p.entity_id;
        button.innerHTML = '<span class="ym-speaker-icon">▣</span><span class="ym-station-copy"><strong></strong><small><i></i><span></span></small></span><span class="ym-selected-mark"></span>';
        box.append(button);
      }
      const selected = p.entity_id === this._selectedPlayerId;
      button.className = `ym-station ${playing(p) ? "playing" : ""} ${selected ? "selected" : ""}`;
      button.setAttribute("aria-pressed", String(selected));
      button.disabled = ["unavailable", "unknown"].includes(p.state);
      button.querySelector("strong").textContent = p.name;
      button.querySelector("small span").textContent = `${stateLabel(p.state)}${p.title ? ` · ${p.title}` : ""}`;
      button.querySelector(".ym-selected-mark").textContent = selected ? "✓" : "";
    }
    for (const [id, button] of buttons) if (!stations.some(p => p.entity_id === id)) button.remove();
    // Retain the exact button nodes across HA state pushes, including during a tap.
    if (this._stationPointer == null) stations.forEach((p, index) => {
      const button = [...box.children].find(node => node.dataset.station === p.entity_id);
      if (box.children[index] !== button) box.insertBefore(button, box.children[index] || null);
    });
  }

  updateNowPlaying() {
    if (!this.querySelector("#ym-now-title")) return;
    const player = this.activePlayer();
    const disabled = !player || ["unavailable", "unknown"].includes(player.state);
    this.querySelector("#ym-player-name").textContent = player?.name || "Выберите колонку";
    this.querySelector("#ym-now-title").textContent = player?.title || "Ничего не играет";
    this.querySelector("#ym-now-artist").textContent = player?.artist || "Выберите музыку в библиотеке";
    const cover = this.querySelector("#ym-cover");
    cover.hidden = !player?.image;
    if (player?.image) cover.src = player.image; else cover.removeAttribute("src");
    const volume = this.querySelector("#ym-volume");
    volume.disabled = disabled || typeof player?.volume !== "number";
    if (this.shadowRoot.activeElement !== volume && !volume.disabled) volume.value = String(player.volume);
    this.querySelector("#ym-volume-value").textContent = volume.disabled ? "—" : `${Math.round(Number(volume.value)*100)}%`;
    const mute = this.querySelector('[data-cmd="mute"]');
    mute.disabled = volume.disabled;
    mute.classList.toggle("active", !!player?.muted);
    mute.setAttribute("aria-label", player?.muted ? "Включить звук" : "Выключить звук");
    this.querySelectorAll(".ym-controls button").forEach(button => { button.disabled = disabled; });
    const play = this.querySelector('[data-cmd="toggle"]');
    const playing = ["playing", "buffering"].includes(player?.state);
    play.textContent = playing ? "❚❚" : "▶";
    play.setAttribute("aria-label", playing ? "Пауза" : "Воспроизвести");
    const seek = this.querySelector("#ym-seek");
    seek.disabled = disabled || !player.duration;
    seek.max = String(player?.duration || 1);
    if (this.shadowRoot.activeElement !== seek) seek.value = String(Math.min(Number(player?.position || 0), Number(seek.max)));
    this.querySelector("#ym-position").textContent = formatTime(seek.value);
    this.querySelector("#ym-duration").textContent = formatTime(player?.duration);
    this.querySelector("#ym-target-label").textContent = this._targets.map(id => this.stations().find(p => p.entity_id === id)?.name).filter(Boolean).join(", ") || "Выберите колонку";
    this.querySelector('[data-action="sources"]').disabled = disabled;
    this.querySelector('[data-action="track-wave"]').disabled = disabled || !/^(?:\d+)(?::\d+)?$|\/track\/\d+/.test(String(player?.media_id || "")) || this._radioBusy;
    const radio = this._radioSessions[player?.entity_id];
    const radioStatus = this.querySelector("#ym-radio-status");
    radioStatus.hidden = !radio;
    radioStatus.textContent = radio ? radio.error || radio.feedback_error || (radio.station.startsWith("track:") ? "Волна по треку · очередь продолжает Home Assistant" : "Моя волна · очередь продолжает Home Assistant") : "";
    const sourceButton = this.querySelector('[data-action="input-source"]');
    sourceButton.disabled = disabled || this._inputSourceBusy;
    this.querySelector("#ym-input-source-name").textContent = this.sourceName(player?.input_source) || (player?.source_list ? "Не выбран" : "Загрузка…");
  }

  sourceName(source) {
    if (!source) return "";
    const entity = this._players.find(player => player.entity_id === source);
    return entity ? `${entity.name} · ${source}` : source;
  }

  async hydrateSource(id, force = false) {
    if (!id) return;
    const state = (!force && this.hass?.states?.[id]) || await this.hass.callApi("GET", `states/${id}`);
    const a = state.attributes || {};
    const info = {input_source:a.source, source_list:Array.isArray(a.source_list) ? a.source_list : []};
    this._sourceInfo.set(id, info);
    this._players = this._players.map(player => player.entity_id === id ? {...player,...info} : player);
    if (this._selectedPlayerId === id) this.updateNowPlaying();
  }

  async openInputSources() {
    const id = this._selectedPlayerId;
    this._inputSourceContext = id;
    this.querySelector("#ym-input-source-options").innerHTML = '<p class="ym-muted">Загрузка источников…</p>';
    this.querySelector("#ym-input-source-error").textContent = "";
    this.querySelector("#ym-input-source-station").textContent = this.activePlayer()?.name || "";
    this.querySelector("#ym-input-source-dialog").showModal();
    try {
      await this.hydrateSource(id);
      if (id !== this._selectedPlayerId) return;
      const player = this.activePlayer();
      this.querySelector("#ym-input-source-options").innerHTML = player.source_list?.length ? player.source_list.map(source => `<button class="ym-input-source-option ${source === player.input_source ? "active" : ""}" data-input-source="${escapeHtml(source)}" aria-pressed="${source === player.input_source}"><span>⇄</span><span>${escapeHtml(this.sourceName(source))}</span><strong>${source === player.input_source ? "✓" : ""}</strong></button>`).join("") : '<p class="ym-muted">Колонка не предоставляет список source. Настройте источники в интеграции Yandex Station.</p>';
    } catch (error) { this.querySelector("#ym-input-source-error").textContent = error.message || error.error || "Не удалось загрузить источники"; }
  }

  async selectInputSource(source) {
    if (this._inputSourceBusy || this._inputSourceContext !== this._selectedPlayerId) return;
    const id = this._selectedPlayerId;
    if (!this.activePlayer()?.source_list?.includes(source)) return;
    this._inputSourceBusy = true;
    this.querySelectorAll("[data-input-source]").forEach(button => { button.disabled = true; });
    this.updateNowPlaying();
    try {
      if (this._radioSessions[id]) await this.radioControl("detach", id);
      await this.media("select_source", {entity_id:[id], source});
      await this.hydrateSource(id, true);
      this.querySelector("#ym-input-source-dialog").close();
      this.notice(`Источник: ${this.sourceName(source)}`);
    } catch (error) { this.querySelector("#ym-input-source-error").textContent = error.body?.message || error.message || error.error || "Не удалось сменить источник"; }
    finally {
      this._inputSourceBusy = false;
      this.querySelectorAll("[data-input-source]").forEach(button => { button.disabled = false; });
      this.updateNowPlaying();
    }
  }

  media(service, data = {}) {
    return this.hass.callApi("POST", `services/media_player/${service}`, {entity_id:[this._selectedPlayerId], ...data});
  }

  async playTracks(tracks, index, targets = this._targets) {
    if (!tracks[index] || this._sending) return;
    const allowed = targets.filter(id => this.stations().some(p => p.entity_id === id && !["unavailable", "unknown"].includes(p.state)));
    if (!allowed.length) { this.showError("Выберите доступную Яндекс-колонку сверху"); return; }
    this._sending = true;
    this.clearError();
    try {
      for (const id of allowed) if (this._radioSessions[id]) await this.radioControl("detach", id);
      // Native Yandex playMusic uses the Yandex stream and speaker metadata.
      await this.media("play_media", {entity_id:allowed, media_content_id:String(tracks[index].id), media_content_type:"track"});
      allowed.forEach(id => {
        this._stationQueues.set(id, {tracks, index});
        this._stationTargets.set(id, [...allowed]);
      });
      if (!allowed.includes(this._selectedPlayerId)) this.selectStation(allowed[0]);
      this.notice(`Воспроизведение: ${allowed.map(id => this.stations().find(p => p.entity_id === id)?.name).join(", ")}`);
      await this.refreshPlayers();
    } catch (error) { this.showError(error); throw error; }
    finally { this._sending = false; }
  }

  async command(action, extra = {}) {
    const player = this.activePlayer();
    if (!player || ["unavailable", "unknown"].includes(player.state)) return;
    this.clearError();
    try {
      if (this._radioSessions[player.entity_id]?.active && ["next", "previous", "stop"].includes(action)) {
        await this.radioControl(action, player.entity_id);
        await this.refreshPlayers();
        return;
      }
      if (action === "next" || action === "previous") {
        const queue = this._stationQueues.get(player.entity_id);
        const current = queue?.tracks[queue.index];
        if (queue && (String(player.media_id || "") === String(current.id) || player.title === current.title)) {
          const index = (queue.index + (action === "next" ? 1 : -1) + queue.tracks.length) % queue.tracks.length;
          await this.playTracks(queue.tracks, index, [player.entity_id]); return;
        }
      }
      const services = {next:"media_next_track", previous:"media_previous_track", toggle:"media_play_pause", stop:"media_stop", seek:"media_seek", volume_set:"volume_set", mute:"volume_mute"};
      const data = action === "volume_set" ? {volume_level:extra.level} : action === "seek" ? {seek_position:extra.position} : action === "mute" ? {is_volume_muted:!player.muted} : {};
      await this.media(services[action], {entity_id:[player.entity_id], ...data});
      if (action === "stop") this._stationQueues.delete(player.entity_id);
      await this.refreshPlayers();
    } catch (error) { this.showError(error); }
  }

  notice(text) {
    const box = this.querySelector("#ym-notice");
    box.textContent = text; box.classList.remove("hidden");
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => box.classList.add("hidden"), 5000);
  }

  openSources() {
    this._sourceContext = this._selectedPlayerId;
    this.querySelector("#ym-source-options").innerHTML = this.stations().map(p => `<label class="ym-source-option"><input type="checkbox" data-source="${escapeHtml(p.entity_id)}" ${this._targets.includes(p.entity_id) ? "checked" : ""} ${["unavailable", "unknown"].includes(p.state) ? "disabled" : ""}><span><strong>${escapeHtml(p.name)}</strong><small>${stateLabel(p.state)}${p.title ? ` · ${escapeHtml(p.title)}` : ""}</small></span></label>`).join("");
    this.querySelector("#ym-sources-error").textContent = "";
    this.querySelector("#ym-sources-dialog").showModal();
  }

  async applySources(sendCurrent = false) {
    const targets = [...this.querySelectorAll("[data-source]:checked")].map(input => input.dataset.source);
    if (!targets.length) { this.querySelector("#ym-sources-error").textContent = "Выберите хотя бы одну колонку"; return; }
    if (this._sourceContext !== this._selectedPlayerId) return;
    const button = this.querySelector('[data-action="send-current"]');
    button.disabled = true;
    try {
      if (sendCurrent) {
        const player = this.activePlayer();
        const state = this.hass?.states?.[player.entity_id] || await this.hass.callApi("GET", `states/${player.entity_id}`);
        const id = String(state?.attributes?.media_content_id || player.media_id || "");
        const match = id.match(/(?:^|\/track\/)(\d+)(?=$|[?:/])/);
        if (!match) throw new Error("У текущего трека нет идентификатора Яндекс Музыки. Выберите трек в библиотеке.");
        await this.playTracks([{id:match[1], title:player.title, artists:player.artist, duration:player.duration}], 0, targets);
      }
      this._targets = targets;
      this._stationTargets.set(this._selectedPlayerId, [...targets]);
      this.updateNowPlaying();
      this.querySelector("#ym-sources-dialog").close();
      if (!sendCurrent) this.notice("Следующий трек будет отправлен на выбранные колонки");
    } catch (error) { this.querySelector("#ym-sources-error").textContent = error.message || error.error || "Не удалось отправить трек"; }
    finally { button.disabled = false; }
  }

  openQueue() {
    const radio = this._radioSessions[this._selectedPlayerId];
    const queue = radio || this._stationQueues.get(this._selectedPlayerId);
    this.querySelector("#ym-queue-title").textContent = `Очередь · ${this.activePlayer()?.name || ""}`;
    this.querySelector("#ym-queue-content").innerHTML = (radio ? `<p class="ym-muted">Бесконечная волна · следующие треки подгружаются автоматически.</p>${radio.error ? `<p role="alert">${escapeHtml(radio.error)}</p>` : ""}${radio.feedback_error ? `<p role="alert">${escapeHtml(radio.feedback_error)}</p>` : ""}` : "") + (queue?.tracks.length ? queue.tracks.map((track,index) => `<button data-queue-index="${index}" class="ym-queue-item ${index === queue.index ? "active" : ""}"><span>${index === queue.index ? "▶" : index+1}</span><span>${escapeHtml(track.title)}<small>${escapeHtml(track.artists || "")}</small></span></button>`).join("") : '<p class="ym-muted">Очередью управляет колонка. Выберите трек или плейлист в библиотеке, чтобы открыть его очередь здесь.</p>');
    this._queueContext = this._selectedPlayerId;
    this.querySelector("#ym-queue-dialog").showModal();
  }

  async search() {
    const query = this.querySelector("#ym-search").value.trim();
    if (this._section === "audiobooks") { await this.loadSection("audiobooks", {query}); return; }
    if (this._section !== "search") { this.filterSection(query); return; }
    await this.loadSection("search", {query});
  }

  async loadWaveSettings(revision) {
    try {
      const data = await this.api("/wave/settings");
      if (revision !== this._sectionRevision) return;
      const select = this.querySelector("#ym-wave-mood");
      select.innerHTML = (data.moods || []).map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.name)}</option>`).join("");
      if (data.mood_energy) select.value = data.mood_energy;
      select.disabled = !data.moods?.length;
      this.querySelector('[data-action="mood-wave"]').disabled = select.disabled;
      if (select.disabled) this.querySelector("#ym-wave-settings-error").textContent = "Яндекс не вернул доступных настроений.";
    } catch (_) {
      if (revision === this._sectionRevision) this.querySelector("#ym-wave-settings-error").textContent = "Не удалось загрузить настройки. Обычную волну можно запустить кнопкой «Слушать».";
    }
  }

  async startWave(byCurrent = false, mood) {
    const id = this._selectedPlayerId;
    if (!id || this._radioBusy) return;
    this._radioBusy = true;
    this.clearError();
    this.querySelectorAll('[data-action="start-wave"], [data-action="track-wave"], [data-action="mood-wave"]').forEach(b => { b.disabled = true; });
    try {
      const body = {entity_id:id, by_current:byCurrent};
      if (mood !== undefined) body.mood_energy = mood;
      const revision = this._radioRevision = (this._radioRevision || 0)+1;
      const data = await this.api("/radio", {method:"POST", body});
      if (revision === this._radioRevision) this._radioSessions = data.radio || {};
      this._stationQueues.delete(id);
      this._stationTargets.set(id, [id]);
      if (this._selectedPlayerId === id) this._targets = [id];
      this.notice(`Волна: ${this.stations().find(p => p.entity_id === id)?.name || id}`);
      await this.refreshPlayers();
    } catch (error) { this.showError(error); }
    finally {
      this._radioBusy = false;
      this.querySelectorAll('[data-action="start-wave"], [data-action="mood-wave"]').forEach(b => { b.disabled = b.dataset.action === "mood-wave" && !!this.querySelector("#ym-wave-mood")?.disabled; });
      this.updateNowPlaying();
    }
  }

  async radioControl(action, id = this._selectedPlayerId, index) {
    const revision = this._radioRevision = (this._radioRevision || 0)+1;
    const data = await this.api("/radio/control", {method:"POST", body:{entity_id:id, action, index}});
    if (revision === this._radioRevision) this._radioSessions = data.radio || {};
    return data.handled;
  }

  onChange(event) {
    if (event.target.id === "ym-volume") this.command("volume_set", {level:Number(event.target.value)});
    if (event.target.id === "ym-seek" && !event.target.disabled) this.command("seek", {position:Number(event.target.value)});
  }

  onClick(event) {
    const suggested = event.target.closest("[data-search-query]");
    if (suggested) { this.loadSection("search", {query:suggested.dataset.searchQuery}); return; }
    const station = event.target.closest("[data-station]");
    if (station) { this.selectStation(station.dataset.station); return; }
    const inputSource = event.target.closest("[data-input-source]");
    if (inputSource) { this.selectInputSource(inputSource.dataset.inputSource); return; }
    const nav = event.target.closest("[data-section]");
    if (nav) { this.loadSection(nav.dataset.section); return; }
    const track = event.target.closest("[data-track-id]");
    if (track) {
      const id = track.dataset.trackId;
      const selected = this._trackMap?.[id];
      const tracks = this._tracks.some(t => String(t.id) === id) ? this._tracks : [selected].filter(Boolean);
      this.playTracks(tracks, tracks.findIndex(t => String(t.id) === id)).catch(() => {}); return;
    }
    const queued = event.target.closest("[data-queue-index]");
    if (queued) {
      const id = this._queueContext;
      if (id !== this._selectedPlayerId) return;
      if (this._radioSessions[id]) this.radioControl("select", id, Number(queued.dataset.queueIndex)).catch(error => this.showError(error));
      else this.playTracks(this._stationQueues.get(id).tracks, Number(queued.dataset.queueIndex), [id]).catch(() => {});
      return;
    }
    const playlist = event.target.closest("[data-playlist-uid]");
    if (playlist) { this.loadSection("playlist", {uid:playlist.dataset.playlistUid, kind:playlist.dataset.playlistKind, title:playlist.dataset.title}); return; }
    const album = event.target.closest("[data-album]");
    if (album) { this.loadSection("album", {id:album.dataset.album, title:album.dataset.title}); return; }
    const cmd = event.target.closest("[data-cmd]");
    if (cmd) { this.command(cmd.dataset.cmd); return; }
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "sources") this.openSources();
    if (action === "input-source") this.openInputSources();
    if (action === "apply-sources") this.applySources();
    if (action === "send-current") this.applySources(true);
    if (action === "queue") this.openQueue();
    if (action === "more-books") this.moreBooks();
    if (action === "close-dialog") event.target.closest("dialog").close();
    if (action === "search") this.search();
    if (action === "play-all") this.playTracks(this._tracks, 0).catch(() => {});
    if (action === "start-wave") this.startWave();
    if (action === "track-wave") this.startWave(true);
    if (action === "mood-wave") this.startWave(false, this.querySelector("#ym-wave-mood").value);
  }
}

const CSS = `
.ym-workspace{overflow-y:auto!important;overflow-x:hidden;display:block!important;scrollbar-gutter:stable;overscroll-behavior-y:auto}.ym-main{overflow:visible!important;min-height:320px;overscroll-behavior:auto!important}.ym-player-area{position:sticky;top:0;z-index:5}.ym-card-row,.ym-stations{overflow-x:auto!important;overflow-y:hidden!important;overscroll-behavior-x:contain}.ym-input-source-button{width:100%;min-height:58px;display:flex;align-items:center;gap:12px;padding:10px 16px;border:1px solid #03a9f480;border-radius:9px;background:#03a9f418;text-align:left;color:#eee}.ym-input-source-button>span:nth-child(2){min-width:0;flex:1}.ym-input-source-button small{display:block;color:#a6cfe3;font-size:11px}.ym-input-source-button strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}.ym-input-source-icon{font-size:30px;color:#29b6f6}.ym-input-source-change{font-size:13px;color:#29b6f6}.ym-input-source-option{display:flex;align-items:center;gap:12px;border:1px solid #444;border-radius:8px;background:transparent;width:100%;min-height:58px;padding:12px;margin:8px 0;text-align:left;overflow-wrap:anywhere}.ym-input-source-option>span:nth-child(2){flex:1;min-width:0}.ym-input-source-option.active{border-color:#03a9f4;background:#03a9f418;color:#29b6f6}.ym-search-welcome{padding:36px 12px;text-align:center;color:#aaa}.ym-search-welcome>span{display:block;font-size:64px;color:#29b6f6}.ym-search-welcome h2{margin:10px 0;color:#eee}.ym-search-welcome p{max-width:400px;margin:0 auto}.ym-search-suggestions{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:22px}.ym-search-suggestions button{min-height:44px;border:1px solid #555;border-radius:24px;padding:8px 16px;background:#292929}
:host{display:block;width:100%;max-width:100%;min-width:0;height:var(--ym-panel-height,100dvh);min-height:0;overflow:hidden;color:#eee;color-scheme:dark;font:14px/1.45 Roboto,Arial,sans-serif;background:#181818;--ym-primary:#03a9f4}
*{box-sizing:border-box}button,input{font:inherit}button{cursor:pointer;color:inherit;touch-action:manipulation}button:disabled{cursor:default;opacity:.4}button:focus-visible,input:focus-visible{outline:2px solid var(--ym-primary);outline-offset:3px}h1,h2,p{margin:0}h1{font-size:26px;font-weight:600}h2{font-size:19px;font-weight:600}strong{font-weight:500}input[type=range]{accent-color:var(--ym-primary);min-height:44px;cursor:pointer;touch-action:pan-y}input[type=checkbox]{accent-color:var(--ym-primary);width:21px;height:21px;flex:none}.hidden,[hidden]{display:none!important}.ym-muted{color:#a6a6a6}
.ym-shell{height:100%;display:grid;grid-template-columns:216px minmax(0,1fr);background:#181818}.ym-sidebar{display:flex;flex-direction:column;padding:24px 12px;overflow:auto;background:#232323;border-right:1px solid #333}.ym-brand{display:flex;align-items:center;gap:10px;padding:0 8px 24px;font-size:17px;font-weight:600}.ym-brand-mark{width:34px;height:34px;background:var(--ym-primary);color:#fff;border-radius:50%;display:grid;place-items:center;font-size:24px;flex:none}.ym-version{display:block;font-size:10px;color:#999;font-weight:400}.ym-nav-caption{padding:20px 14px 8px;color:#a0a0a0;font-size:12px}.ym-nav{display:flex;align-items:center;gap:14px;border:0;border-radius:7px;min-height:48px;padding:10px 14px;text-align:left;background:transparent;color:#ddd}.ym-nav>span{width:24px;font-size:24px;text-align:center}.ym-nav:hover{background:#303030}.ym-nav.active{background:#03a9f420;color:#29b6f6}.ym-account{margin-top:auto;padding:24px 14px 0;font-size:12px;color:#999;overflow-wrap:anywhere}
.ym-workspace{display:grid;grid-template-rows:auto minmax(0,1fr);min-width:0;min-height:0}.ym-player-area{padding:16px 24px 0;background:#202020;border-bottom:1px solid #363636;min-width:0;max-height:52vh;overflow:auto}.ym-stations-heading{display:flex;align-items:center;gap:16px;margin-bottom:10px}.ym-stations-heading h2{font-size:15px}.ym-stations-heading>span{font-size:12px;color:#999}.ym-stations{display:flex;gap:8px;overflow-x:auto;padding:2px 2px 8px;scrollbar-width:thin;scroll-snap-type:x proximity}.ym-station{display:flex;align-items:center;gap:10px;flex:1 0 180px;max-width:330px;min-width:0;min-height:64px;border:1px solid #404040;border-radius:9px;background:#292929;padding:10px 12px;text-align:left;scroll-snap-align:start}.ym-station.selected{border-color:var(--ym-primary);background:#03a9f412}.ym-speaker-icon{font-size:27px;color:#aaa}.ym-station.selected .ym-speaker-icon,.ym-selected-mark{color:var(--ym-primary)}.ym-station-copy{flex:1;min-width:0}.ym-station-copy strong,.ym-station-copy small{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.ym-station-copy small{font-size:11px;color:#aaa;margin-top:4px}.ym-station-copy i{display:inline-block;width:6px;height:6px;border-radius:50%;background:#777;margin-right:5px}.ym-station.playing .ym-station-copy i{background:#4caf50}.ym-station.playing{box-shadow:inset 0 3px #4caf50}
.ym-player{display:grid;grid-template-columns:minmax(180px,1fr) minmax(180px,1fr) auto;gap:8px 18px;padding:12px 0 10px}.ym-now{display:flex;align-items:center;gap:12px;min-width:0}.ym-artwork{position:relative;width:64px;height:64px;flex:none;background:#333;border-radius:7px;display:grid;place-items:center;color:#999;font-size:30px;overflow:hidden}.ym-artwork img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.ym-now-copy{min-width:0}.ym-now-copy>span,.ym-now-copy>strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ym-now-copy>strong{font-size:16px;margin:2px 0}.ym-now-copy>.ym-muted{font-size:12px}.ym-player-name{font-size:11px;color:#29b6f6}.ym-transport{min-width:0;align-self:center}.ym-controls{display:flex;align-items:center;justify-content:center;gap:6px}.ym-controls button,.ym-icon-button{border:0;background:transparent;width:44px;height:44px;min-width:44px;display:inline-grid;place-items:center;border-radius:50%;font-size:20px}.ym-controls button:hover,.ym-icon-button:hover{background:#ffffff12}.ym-controls .ym-play{background:var(--ym-primary);color:#fff;width:48px;height:48px;font-size:23px}.ym-icon-button.active{color:#29b6f6;background:#03a9f420}.ym-timeline{display:flex;align-items:center;gap:8px;color:#aaa;font-size:10px;height:32px}.ym-timeline input{flex:1;min-width:0;width:100%;margin:0}.ym-timeline span{font-variant-numeric:tabular-nums}.ym-player-actions{display:flex;align-items:center;gap:4px}.ym-action{display:flex;align-items:center;gap:8px;text-align:left;min-height:48px;border:0;background:transparent;border-radius:7px;padding:6px 8px;color:#ddd}.ym-action:hover{background:#ffffff0b}.ym-action>span{font-size:12px;max-width:180px}.ym-action small{display:block;color:#29b6f6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:170px;font-size:11px}.ym-volume{grid-column:1/-1;display:flex;align-items:center;gap:8px;border-top:1px solid #ffffff09;padding-top:2px;min-width:0}.ym-volume label{font-size:11px;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px}.ym-volume input{width:180px;min-width:80px;margin:0}.ym-mobile-stop{display:none}.ym-volume output{font-size:11px;color:#aaa;width:36px;font-variant-numeric:tabular-nums}
.ym-main{min-height:0;overflow:auto;overscroll-behavior:contain;padding:24px;min-width:0}.ym-header{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.ym-search{display:flex;align-items:center;gap:8px;background:#292929;border:1px solid #404040;border-radius:8px;min-width:220px;max-width:440px;flex:1;padding-left:12px}.ym-search>span{font-size:24px;color:#aaa}.ym-search input{width:100%;min-width:0;min-height:44px;border:0;background:transparent;color:#eee;outline:none;font-size:14px}.ym-search button{align-self:stretch;border:0;border-left:1px solid #404040;background:transparent;padding:0 12px;color:#29b6f6;border-radius:0 7px 7px 0}.ym-error{padding:12px 16px;background:#572326;color:#ffcdd2;border-radius:7px;margin-bottom:16px}.ym-notice{padding:10px 14px;background:#03a9f415;color:#81d4fa;border-radius:7px;margin-bottom:12px}.ym-loading,.ym-empty{padding:24px;color:#aaa;text-align:center}.ym-wave-banner{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px;border-radius:10px;background:linear-gradient(120deg,#0d4770,#283457);margin-bottom:28px}.ym-wave-banner p{color:#b4cddd;font-size:13px;margin-top:4px}.ym-primary,.ym-secondary{min-height:44px;min-width:44px;border:0;border-radius:22px;padding:10px 20px;background:var(--ym-primary);color:#fff;font-weight:500}.ym-secondary{background:#393939}.ym-primary:hover{filter:brightness(1.1)}.ym-shelf{margin-bottom:28px}.ym-section-head{display:flex;align-items:center;justify-content:space-between;margin:20px 0 14px;gap:12px}.ym-link{background:transparent;border:0;color:#29b6f6;min-height:44px}.ym-card-row{display:grid;grid-auto-flow:column;grid-auto-columns:160px;gap:16px;overflow:auto;scroll-snap-type:x proximity;scrollbar-width:thin;padding-bottom:8px}.ym-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:20px}.ym-card{background:transparent;border:0;padding:0;text-align:left;min-width:0;scroll-snap-align:start}.ym-card-art{aspect-ratio:1;position:relative;overflow:hidden;border-radius:8px;background:linear-gradient(135deg,#315975,#364053);display:grid;place-items:center;font-size:48px;color:#a5c7df}.ym-card-art img{width:100%;height:100%;object-fit:cover}.ym-card>strong{display:block;font-size:14px;margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ym-card>small{display:block;color:#999;margin-top:3px;font-size:12px}.ym-card-play{position:absolute;bottom:10px;right:10px;background:var(--ym-primary);color:#fff;border-radius:50%;width:40px;height:40px;font-size:18px;display:grid;place-items:center;opacity:0;transition:opacity .15s}.ym-card:hover .ym-card-play,.ym-card:focus-visible .ym-card-play{opacity:1}.ym-list-toolbar{display:flex;align-items:center;justify-content:space-between;margin:0 0 16px;color:#999}.ym-track{display:grid;grid-template-columns:28px 44px minmax(0,1fr) 44px 24px;align-items:center;gap:12px;width:100%;min-height:60px;background:transparent;border:0;border-bottom:1px solid #ffffff06;border-radius:5px;padding:6px;text-align:left}.ym-track:hover{background:#ffffff09}.ym-track-number,.ym-track-time{font-size:12px;color:#999}.ym-track-art{width:44px;height:44px;background:#333;border-radius:4px;overflow:hidden;display:grid;place-items:center;color:#888}.ym-track-art img{width:100%;height:100%;object-fit:cover}.ym-track-main{min-width:0}.ym-track-main strong,.ym-track-main small{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.ym-track-main small{font-size:12px;color:#999;margin-top:3px}.ym-track-play{color:var(--ym-primary);opacity:0}.ym-track:hover .ym-track-play{opacity:1}
.ym-dialog{color:#eee;background:#272727;border:1px solid #444;border-radius:14px;padding:22px;width:min(460px,calc(100% - 24px));max-height:85dvh;overflow:auto;overscroll-behavior:contain;box-shadow:0 16px 80px #0008}.ym-dialog::backdrop{background:#0009}.ym-dialog-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.ym-dialog>p{font-size:13px;margin:10px 0 16px}.ym-source-option{display:flex;align-items:center;gap:12px;min-height:70px;padding:10px 4px;border-bottom:1px solid #3c3c3c;cursor:pointer}.ym-source-option>span{min-width:0}.ym-source-option strong,.ym-source-option small{display:block}.ym-source-option small{color:#999;font-size:12px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:310px}.ym-inline-error{color:#ef9a9a}.ym-dialog-buttons{display:flex;flex-direction:column;gap:10px;margin-top:20px}.ym-queue-item{display:flex;align-items:center;gap:12px;background:transparent;border:0;border-bottom:1px solid #333;width:100%;min-height:60px;text-align:left;padding:8px}.ym-queue-item.active{color:#29b6f6}.ym-queue-item small{display:block;color:#999;font-size:12px}
@media(max-width:1100px){.ym-shell{grid-template-columns:190px minmax(0,1fr)}.ym-player{grid-template-columns:minmax(160px,1fr) auto}.ym-player-actions{grid-column:1;grid-row:2}.ym-volume{grid-column:2;grid-row:2;border:0;padding:0}.ym-volume label{display:none}.ym-volume input{width:110px}.ym-player-area{padding:12px 18px 0}.ym-main{padding:20px}}
@media(max-width:800px){.ym-shell{grid-template-columns:1fr;grid-template-rows:56px minmax(0,1fr)}.ym-sidebar{padding:4px 8px;flex-direction:row;align-items:center;gap:4px;overflow:auto;border:0;border-bottom:1px solid #333;scrollbar-width:none}.ym-brand{padding:0;margin-right:6px}.ym-brand>span:last-child,.ym-nav-caption,.ym-account{display:none}.ym-brand-mark{width:30px;height:30px}.ym-nav{min-height:44px;flex:none;padding:6px 10px;white-space:nowrap;gap:7px;font-size:13px}.ym-nav>span{font-size:19px;width:20px}.ym-workspace{grid-row:2}.ym-player-area{padding:10px 12px 0;max-height:52dvh}.ym-stations-heading{margin-bottom:6px}.ym-stations-heading>span{display:none}.ym-station{flex:0 0 180px;min-height:58px;padding:8px 10px}.ym-station-copy strong{font-size:13px}.ym-player{gap:2px 8px;padding-top:8px;grid-template-columns:minmax(0,1fr) auto}.ym-now{gap:9px}.ym-artwork{width:48px;height:48px}.ym-now-copy>strong{font-size:14px}.ym-now-copy>.ym-muted{font-size:11px}.ym-controls{gap:0}.ym-controls button{width:44px;height:44px;min-width:44px;font-size:18px}.ym-controls [data-cmd=stop]{display:none}.ym-mobile-stop{display:inline-grid}.ym-controls .ym-play{width:46px;height:46px}.ym-transport{display:contents}.ym-timeline{grid-column:1/-1;grid-row:2;height:28px}.ym-player-actions{grid-column:1;grid-row:4}.ym-action{min-height:44px;padding:4px;font-size:16px}.ym-action>span{font-size:11px;max-width:190px}.ym-action small{max-width:180px}.ym-volume{grid-column:1/-1;grid-row:3;gap:7px}.ym-volume input{flex:1;width:100%;min-width:0}.ym-volume label{display:block;max-width:115px;font-size:10px}.ym-main{padding:18px 12px}.ym-header{display:block;margin-bottom:18px}h1{font-size:23px}h2{font-size:18px}.ym-search{max-width:none;min-width:0;margin-top:12px}.ym-wave-banner{padding:16px;margin-bottom:20px}.ym-wave-banner h2{font-size:20px}.ym-wave-banner p{font-size:12px}.ym-wave-banner .ym-primary{flex:none;padding:10px 14px}.ym-card-row{grid-auto-columns:140px;gap:12px}.ym-card-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 12px}.ym-track{grid-template-columns:20px 40px minmax(0,1fr) 38px;gap:8px;min-height:58px}.ym-track-art{width:40px;height:40px}.ym-track-play{display:none}.ym-track-main strong{font-size:13px}.ym-track-time{font-size:11px}.ym-dialog{position:fixed;inset:auto 0 0;margin:0;width:100%;max-width:100%;max-height:85dvh;border-radius:16px 16px 0 0;padding:16px 18px max(20px,env(safe-area-inset-bottom))}.ym-source-option small{max-width:calc(100vw - 100px)}}
@media(max-height:600px) and (max-width:800px){.ym-player-area{max-height:60dvh}.ym-stations-heading{display:none}.ym-station{min-height:48px}.ym-player-actions{grid-row:3;grid-column:1}.ym-volume{grid-row:3;grid-column:2}.ym-volume label{display:none}.ym-volume input{min-width:60px}.ym-timeline{height:22px}.ym-player{padding-bottom:0}.ym-now-copy>.ym-muted{display:none}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media(max-width:800px){.ym-input-source-button{min-height:56px;padding:8px 10px;gap:8px}.ym-input-source-button strong{font-size:13px}.ym-input-source-change{font-size:11px;max-width:72px}.ym-player-area{max-height:58dvh}.ym-main{min-height:calc(100dvh - 360px)}}
@media(max-height:600px){.ym-player-area{position:relative;max-height:none}.ym-input-source-button{min-height:48px}.ym-workspace{scrollbar-gutter:auto}}
.ym-volume input{flex:1;width:100%;min-width:0}
#ym-volume{-webkit-appearance:none;appearance:none;background:transparent;min-height:44px;touch-action:pan-y}
#ym-volume::-webkit-slider-runnable-track{height:8px;background:#555;border-radius:8px}
#ym-volume::-webkit-slider-thumb{-webkit-appearance:none;width:24px;height:24px;margin-top:-8px;background:var(--ym-primary);border:3px solid #202020;border-radius:50%}
#ym-volume::-moz-range-track{height:8px;background:#555;border-radius:8px}
#ym-volume::-moz-range-progress{height:8px;background:var(--ym-primary);border-radius:8px}
#ym-volume::-moz-range-thumb{width:20px;height:20px;background:var(--ym-primary);border:2px solid #202020;border-radius:50%}
.ym-wave-settings{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:24px}.ym-wave-settings p{flex-basis:100%;font-size:12px}.ym-wave-settings select{min-height:44px;min-width:140px;max-width:100%;font:inherit;border:1px solid #555;border-radius:8px;background:#292929;color:#eee;padding:8px}
.ym-radio-status{grid-column:1/-1;color:#aaa;font-size:12px;padding:4px 0}
@media(min-width:801px) and (max-width:1100px){.ym-volume{grid-column:1/-1;grid-row:3}}
@media(max-width:800px){
  .ym-player-area{position:relative;max-height:none;overflow:visible}
  .ym-player{grid-template-columns:minmax(0,1fr);gap:4px;padding:8px 0}
  .ym-now{grid-column:1;grid-row:1;gap:8px}
  .ym-artwork{width:40px;height:40px}
  .ym-now-copy{flex:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.7fr);align-items:center;gap:0 6px}
  .ym-now-copy .ym-player-name{grid-column:1/-1}
  .ym-now-copy>strong{margin:0;font-size:13px}
  .ym-now-copy>.ym-muted{display:block;font-size:11px}
  .ym-transport{display:contents}
  .ym-controls{grid-column:1;grid-row:2;gap:16px;min-width:0}
  .ym-controls [data-cmd=stop]{display:inline-grid}
  .ym-controls button{flex:none}
  .ym-timeline{grid-column:1;grid-row:3;height:44px}
  .ym-volume{grid-column:1;grid-row:4;gap:8px;padding:0;border:0}
  .ym-volume input{width:100%;min-width:0}
  .ym-player-actions{grid-column:1;grid-row:5;justify-content:space-between;gap:4px}
  .ym-action>span{max-width:180px}
  .ym-input-source-button{min-height:48px}
  .ym-wave-banner{flex-wrap:wrap}
  .ym-wave-settings{align-items:stretch}
}
`;

function stateLabel(state) { return ({playing:"\u0418\u0433\u0440\u0430\u0435\u0442",buffering:"\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430",paused:"\u041f\u0430\u0443\u0437\u0430",idle:"\u041d\u0435 \u0438\u0433\u0440\u0430\u0435\u0442",off:"\u0412\u044b\u043a\u043b\u044e\u0447\u0435\u043d\u0430",unavailable:"\u041d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430",unknown:"\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438"})[state] || "\u0413\u043e\u0442\u043e\u0432\u0430"; }
function formatTime(seconds) { const value = Number(seconds || 0); return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}`; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char])); }
if (!customElements.get("yandex-music-chaos-panel")) {
  customElements.define("yandex-music-chaos-panel", YandexMusicChaosPanel);
}
