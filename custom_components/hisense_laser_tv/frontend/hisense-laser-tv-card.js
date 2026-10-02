const CARD_TAG = "hisense-laser-tv-card";

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

class HisenseLaserTvCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._signature = "";
    this._busy = false;
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { filter: { domain: "media_player" } } },
        },
        {
          name: "wake_button",
          selector: { entity: { filter: { domain: "button" } } },
        },
        { name: "name", selector: { text: {} } },
      ],
      computeLabel: (schema) =>
        ({
          entity: "TV",
          wake_button: "Pulsante accensione Wi-Fi",
          name: "Nome personalizzato",
        })[schema.name],
    };
  }

  static getStubConfig() {
    return { entity: "media_player.hisense_laser_tv" };
  }

  setConfig(config) {
    if (!config.entity || !String(config.entity).startsWith("media_player.")) {
      throw new Error("Seleziona l'entita media_player della Hisense Laser TV");
    }
    this._config = { ...config };
    this._signature = "";
    this._render(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return {
      columns: 12,
      rows: 4,
      min_columns: 6,
      min_rows: 3,
    };
  }

  _wakeButtonEntity(mediaState) {
    const configured = this._config?.wake_button;
    if (configured && this._hass?.states[configured]) {
      return configured;
    }

    const mediaMac = mediaState?.attributes?.mac_address;
    return Object.values(this._hass?.states || {}).find((state) => {
      if (!state.entity_id.startsWith("button.")) return false;
      const name = String(state.attributes?.friendly_name || "").toLowerCase();
      const sameMac = mediaMac && state.attributes?.mac_address === mediaMac;
      return sameMac || name.includes("accendi tramite wi-fi");
    })?.entity_id;
  }

  _stateSignature(mediaState, wakeEntity) {
    if (!mediaState) return `missing:${this._config?.entity}`;
    const attributes = mediaState.attributes || {};
    return JSON.stringify([
      mediaState.state,
      attributes.friendly_name,
      attributes.volume_level,
      attributes.is_volume_muted,
      attributes.source,
      attributes.source_list,
      attributes.wifi_wake_configured,
      wakeEntity,
      wakeEntity ? this._hass.states[wakeEntity]?.state : null,
      this._config?.name,
      this._busy,
    ]);
  }

  _render(force = false) {
    if (!this.shadowRoot || !this._config || !this._hass) return;

    const mediaState = this._hass.states[this._config.entity];
    const wakeEntity = this._wakeButtonEntity(mediaState);
    const signature = this._stateSignature(mediaState, wakeEntity);
    if (!force && signature === this._signature) return;
    this._signature = signature;

    if (!mediaState) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div class="missing">Entita non trovata: ${escapeHtml(this._config.entity)}</div>
        </ha-card>
        ${this._styles()}
      `;
      return;
    }

    const attributes = mediaState.attributes || {};
    const isOn = !["off", "unavailable", "unknown"].includes(mediaState.state);
    const isOff = mediaState.state === "off";
    const isUnavailable = ["unavailable", "unknown"].includes(mediaState.state);
    const canWake = Boolean(
      attributes.wifi_wake_configured ||
        (wakeEntity && this._hass.states[wakeEntity]?.state !== "unavailable"),
    );
    const volume = Math.round(Number(attributes.volume_level || 0) * 100);
    const muted = Boolean(attributes.is_volume_muted);
    const sources = Array.isArray(attributes.source_list)
      ? attributes.source_list
      : [];
    const currentSource = attributes.source || "";
    const title =
      this._config.name || attributes.friendly_name || "Hisense Laser TV";
    const status = isOn
      ? "Accesa"
      : isOff
        ? "Spenta"
        : isUnavailable
          ? "Non raggiungibile"
          : mediaState.state;
    const powerLabel = isOn ? "Spegni" : "Accendi tramite Wi-Fi";
    const powerIcon = isOn ? "mdi:power-standby" : "mdi:power";

    const sourceButtons = sources
      .map(
        (source, index) => `
          <button
            class="source ${source === currentSource ? "selected" : ""}"
            data-source-index="${index}"
            ${isOn ? "" : "disabled"}
            title="Passa a ${escapeHtml(source)}"
          >${escapeHtml(source)}</button>
        `,
      )
      .join("");

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="card-content">
          <header>
            <div class="identity">
              <ha-icon icon="mdi:projector"></ha-icon>
              <div class="titles">
                <div class="name">${escapeHtml(title)}</div>
                <div class="status ${isOn ? "online" : ""}">${escapeHtml(status)}</div>
              </div>
            </div>
            <button
              class="icon-button power ${isOn ? "active" : ""}"
              id="power"
              title="${powerLabel}"
              aria-label="${powerLabel}"
              ${this._busy || (!isOn && !canWake && isUnavailable) ? "disabled" : ""}
            ><ha-icon icon="${powerIcon}"></ha-icon></button>
          </header>

          ${
            !canWake && !isOn
              ? `<div class="notice">
                  <ha-icon icon="mdi:wifi-alert"></ha-icon>
                  Configura il MAC Wi-Fi nell'integrazione per abilitare l'accensione.
                </div>`
              : ""
          }

          <section class="volume-section ${isOn ? "" : "disabled-section"}">
            <button
              class="icon-button"
              id="mute"
              title="${muted ? "Riattiva audio" : "Disattiva audio"}"
              aria-label="${muted ? "Riattiva audio" : "Disattiva audio"}"
              ${isOn ? "" : "disabled"}
            ><ha-icon icon="${muted ? "mdi:volume-off" : "mdi:volume-high"}"></ha-icon></button>
            <input
              id="volume"
              type="range"
              min="0"
              max="100"
              step="1"
              value="${volume}"
              aria-label="Volume"
              ${isOn ? "" : "disabled"}
            />
            <output id="volume-value">${volume}%</output>
          </section>

          <section class="sources-section ${sources.length ? "" : "empty"}">
            <div class="section-label">Ingressi</div>
            <div class="sources">
              ${
                sourceButtons ||
                `<span class="empty-message">Disponibili quando la TV e accesa</span>`
              }
            </div>
          </section>
        </div>
      </ha-card>
      ${this._styles()}
    `;

    this.shadowRoot.getElementById("power")?.addEventListener("click", () =>
      this._handlePower(mediaState, wakeEntity),
    );
    this.shadowRoot.getElementById("mute")?.addEventListener("click", () =>
      this._callService("media_player", "volume_mute", {
        entity_id: this._config.entity,
        is_volume_muted: !muted,
      }),
    );

    const volumeSlider = this.shadowRoot.getElementById("volume");
    volumeSlider?.addEventListener("input", (event) => {
      const output = this.shadowRoot.getElementById("volume-value");
      if (output) output.textContent = `${event.target.value}%`;
    });
    volumeSlider?.addEventListener("change", (event) =>
      this._callService("media_player", "volume_set", {
        entity_id: this._config.entity,
        volume_level: Number(event.target.value) / 100,
      }),
    );

    this.shadowRoot.querySelectorAll("[data-source-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const source = sources[Number(button.dataset.sourceIndex)];
        if (source) {
          this._callService("media_player", "select_source", {
            entity_id: this._config.entity,
            source,
          });
        }
      });
    });
  }

  async _handlePower(mediaState, wakeEntity) {
    if (this._busy) return;
    this._busy = true;
    this._render(true);
    try {
      const isOn = !["off", "unavailable", "unknown"].includes(mediaState.state);
      if (isOn) {
        await this._callService("media_player", "turn_off", {
          entity_id: this._config.entity,
        });
      } else if (
        wakeEntity &&
        this._hass.states[wakeEntity]?.state !== "unavailable"
      ) {
        await this._callService("button", "press", { entity_id: wakeEntity });
      } else {
        await this._callService("media_player", "turn_on", {
          entity_id: this._config.entity,
        });
      }
    } finally {
      this._busy = false;
      this._signature = "";
      this._render(true);
    }
  }

  _callService(domain, service, data) {
    return this._hass.callService(domain, service, data);
  }

  _styles() {
    return `
      <style>
        :host {
          display: block;
          letter-spacing: 0;
        }
        ha-card {
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 8px);
        }
        .card-content {
          padding: 16px;
          display: grid;
          gap: 16px;
        }
        header,
        .identity,
        .volume-section {
          display: flex;
          align-items: center;
        }
        header {
          justify-content: space-between;
          gap: 16px;
        }
        .identity {
          gap: 12px;
          min-width: 0;
        }
        .identity > ha-icon {
          --mdc-icon-size: 28px;
          color: var(--primary-color);
          flex: 0 0 auto;
        }
        .titles {
          min-width: 0;
        }
        .name {
          color: var(--primary-text-color);
          font-size: 18px;
          font-weight: 600;
          line-height: 1.25;
          overflow-wrap: anywhere;
        }
        .status {
          color: var(--secondary-text-color);
          font-size: 13px;
          margin-top: 2px;
        }
        .status.online {
          color: var(--success-color, #2e7d32);
        }
        button {
          font: inherit;
          letter-spacing: 0;
        }
        .icon-button {
          width: 40px;
          height: 40px;
          border: 0;
          border-radius: 50%;
          display: inline-grid;
          place-items: center;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          cursor: pointer;
          flex: 0 0 auto;
        }
        .icon-button:hover:not(:disabled) {
          background: var(--divider-color);
        }
        .icon-button.power.active {
          background: var(--error-color);
          color: var(--text-primary-color, #fff);
        }
        button:disabled,
        input:disabled {
          cursor: default;
          opacity: 0.4;
        }
        .notice {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          border-left: 3px solid var(--warning-color, #f9a825);
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
          font-size: 13px;
        }
        .notice ha-icon {
          color: var(--warning-color, #f9a825);
          flex: 0 0 auto;
        }
        .volume-section {
          gap: 12px;
          min-width: 0;
        }
        input[type="range"] {
          width: 100%;
          min-width: 80px;
          accent-color: var(--primary-color);
        }
        output {
          width: 44px;
          text-align: right;
          color: var(--primary-text-color);
          font-variant-numeric: tabular-nums;
          font-size: 14px;
        }
        .disabled-section {
          opacity: 0.55;
        }
        .sources-section {
          min-width: 0;
        }
        .section-label {
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 600;
          margin-bottom: 8px;
          text-transform: uppercase;
        }
        .sources {
          display: flex;
          gap: 8px;
          overflow-x: auto;
          padding-bottom: 2px;
          scrollbar-width: thin;
        }
        .source {
          min-height: 36px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          padding: 0 12px;
          background: transparent;
          color: var(--primary-text-color);
          white-space: nowrap;
          cursor: pointer;
        }
        .source:hover:not(:disabled) {
          border-color: var(--primary-color);
        }
        .source.selected {
          border-color: var(--primary-color);
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }
        .empty-message,
        .missing {
          color: var(--secondary-text-color);
          font-size: 14px;
        }
        .missing {
          padding: 16px;
        }
        @media (max-width: 420px) {
          .card-content {
            padding: 14px;
            gap: 14px;
          }
          .name {
            font-size: 16px;
          }
        }
      </style>
    `;
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, HisenseLaserTvCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: "Hisense Laser TV",
    description: "Accensione Wi-Fi, volume e selezione rapida degli ingressi.",
    preview: true,
    getEntitySuggestion: (hass, entityId) => {
      const state = hass.states[entityId];
      if (
        !entityId.startsWith("media_player.") ||
        !state?.attributes?.client_version
      ) {
        return null;
      }
      return {
        config: { type: `custom:${CARD_TAG}`, entity: entityId },
      };
    },
  });
}
