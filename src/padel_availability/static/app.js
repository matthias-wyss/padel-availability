(() => {
  const timezone = "Europe/Zurich";
  const storageKey = "padelAvailability.selectedLocations";
  const dateFormatter = new Intl.DateTimeFormat("fr-CH", {
    timeZone: timezone,
    dateStyle: "full",
  });
  const dateShortFormatter = new Intl.DateTimeFormat("fr-CH", {
    timeZone: timezone,
    dateStyle: "medium",
  });
  const datePartsFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const timeFormatter = new Intl.DateTimeFormat("fr-CH", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const dateFrom = document.querySelector("#date-from");
  const dateTo = document.querySelector("#date-to");
  const timeFrom = document.querySelector("#time-from");
  const timeTo = document.querySelector("#time-to");
  const clubList = document.querySelector("#club-list");
  const clubSearch = document.querySelector("#club-search");
  const refreshButton = document.querySelector("#refresh-button");
  const refreshMessage = document.querySelector("#refresh-message");
  const locationStatuses = document.querySelector("#location-status-results");
  let locations = [];
  let selectedLocationIds = new Set();
  let availabilityGeneratedAt = 0;
  let reloadedRefreshJobId = null;
  let refreshTimer;

  function localDate(value) {
    const parts = Object.fromEntries(
      datePartsFormatter.formatToParts(new Date(value)).map(({ type, value: part }) => [type, part]),
    );
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function shiftDate(value, days) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
  }

  function formatTime(value) {
    return timeFormatter.format(new Date(value));
  }

  function formatDate(value) {
    return dateFormatter.format(new Date(`${value}T12:00:00Z`));
  }

  function formatDateTime(value) {
    return new Intl.DateTimeFormat("fr-CH", {
      timeZone: timezone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  }

  function today() {
    return localDate(new Date().toISOString());
  }

  function selectedIds() {
    return selectedLocationIds;
  }

  function savedIds(allIds) {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved === null) return new Set(allIds);
      const parsed = JSON.parse(saved);
      return Array.isArray(parsed) ? new Set(parsed.filter((id) => allIds.includes(id))) : new Set(allIds);
    } catch {
      return new Set(allIds);
    }
  }

  function normalize(value) {
    return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("fr-CH");
  }

  function renderClubList() {
    clubList.replaceChildren();
    const query = normalize(clubSearch.value.trim());
    const sorted = [...locations].sort((a, b) =>
      `${a.municipality} ${a.canonical_name}`.localeCompare(
        `${b.municipality} ${b.canonical_name}`,
        "fr-CH",
      ),
    );
    let groupName = null;
    let group;
    for (const location of sorted) {
      const municipality = location.municipality || "Autre";
      const labelText = `${location.canonical_name} ${municipality}`;
      if (query && !normalize(labelText).includes(query)) continue;
      if (municipality !== groupName) {
        groupName = municipality;
        group = document.createElement("div");
        group.className = "municipality-group";
        const heading = document.createElement("p");
        heading.className = "club-municipality-heading";
        heading.textContent = municipality;
        group.append(heading);
        clubList.append(group);
      }
      const label = document.createElement("label");
      label.className = "club-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = `club-${location.location_id}`;
      checkbox.value = location.location_id;
      checkbox.checked = selectedLocationIds.has(location.location_id);
      const text = document.createElement("span");
      text.innerHTML = `<span class="club-name"></span><span class="club-municipality"></span>`;
      text.querySelector(".club-name").textContent = location.canonical_name;
      text.querySelector(".club-municipality").textContent = municipality;
      label.append(checkbox, text);
      group.append(label);
    }
    document.querySelector("#club-count").textContent = `${selectedIds().size}/${locations.length}`;
  }

  function coverMatches(location) {
    const selected = new Set(
      [...document.querySelectorAll("input[name=cover]:checked")].map((input) => input.value),
    );
    if (location.overall_cover_status === "indoor") return selected.has("indoor");
    if (location.overall_cover_status === "outdoor") return selected.has("outdoor");
    return selected.has("other");
  }

  function matchesFilters(slot) {
    const day = localDate(slot.starts_at);
    if (dateFrom.value && day < dateFrom.value) return false;
    if (dateTo.value && day > dateTo.value) return false;
    if (timeFrom.value && timeTo.value) {
      const start = formatTime(slot.starts_at);
      if (start < timeFrom.value || start >= timeTo.value) return false;
    }
    return true;
  }

  function coverLabel(status) {
    return {
      indoor: "Intérieur",
      outdoor: "Extérieur",
      partially_covered: "Partiellement couvert",
      seasonal: "Saisonnier",
      unknown: "Couverture inconnue",
    }[status] || "Couverture inconnue";
  }

  function createSlotCard(location, slot, state) {
    const article = document.createElement("article");
    article.className = `slot-card${state === "unknown" ? " is-unknown" : ""}${state === "stale" ? " is-stale" : ""}`;
    article.dataset.locationId = location.location_id;

    const main = document.createElement("div");
    main.className = "slot-main";
    const title = document.createElement("h4");
    title.textContent = location.canonical_name;
    const municipality = document.createElement("p");
    municipality.className = "slot-location";
    municipality.textContent = location.municipality;
    const time = document.createElement("p");
    time.className = "slot-time";
    const start = document.createElement("time");
    start.dateTime = slot.starts_at;
    start.textContent = formatTime(slot.starts_at);
    const separator = document.createElement("span");
    separator.className = "slot-time-separator";
    separator.textContent = "à";
    const end = document.createElement("time");
    end.dateTime = slot.ends_at;
    end.textContent = formatTime(slot.ends_at);
    time.append(start, separator, end);

    const duration = Math.max(0, Math.round((Date.parse(slot.ends_at) - Date.parse(slot.starts_at)) / 60000));
    const durationText = document.createElement("span");
    durationText.className = "slot-duration";
    durationText.textContent = `${duration} min`;

    const badges = document.createElement("div");
    badges.className = "slot-badges";
    const stateBadge = document.createElement("span");
    stateBadge.className = `status-badge${state === "unknown" ? " unknown" : ""}${state === "stale" ? " stale" : ""}`;
    stateBadge.textContent = state === "unknown" ? "À vérifier" : state === "stale" ? "Données anciennes" : "Disponible";
    const cover = document.createElement("span");
    cover.className = "cover-label";
    cover.textContent = coverLabel(location.overall_cover_status);
    badges.append(stateBadge, cover);

    main.append(title, municipality);
    if (slot.court_label) {
      const court = document.createElement("p");
      court.className = "slot-court";
      court.textContent = slot.court_label;
      main.append(court);
    }
    main.append(time, durationText, badges);
    if (location.last_success_at) {
      const freshness = document.createElement("p");
      freshness.className = "slot-freshness";
      freshness.textContent = state === "stale"
        ? `Dernière donnée fiable : ${formatDateTime(location.last_success_at)}`
        : `Mis à jour : ${formatDateTime(location.last_success_at)}`;
      main.append(freshness);
    }

    article.append(main);
    if (location.booking_url) {
      const booking = document.createElement("a");
      booking.className = "booking-link";
      booking.href = location.booking_url;
      booking.target = "_blank";
      booking.rel = "noopener noreferrer";
      booking.textContent = "Réserver";
      article.append(booking);
    }
    return article;
  }

  function renderSlotGroups(container, rows, state) {
    container.replaceChildren();
    rows.sort((a, b) => Date.parse(a.slot.starts_at) - Date.parse(b.slot.starts_at));
    let groupDate = null;
    let group;
    for (const row of rows) {
      const day = localDate(row.slot.starts_at);
      if (day !== groupDate) {
        groupDate = day;
        group = document.createElement("div");
        group.className = "date-group";
        const heading = document.createElement("h4");
        heading.className = "date-group-title";
        heading.textContent = formatDate(day);
        group.append(heading);
        container.append(group);
      }
      group.append(createSlotCard(row.location, row.slot, state));
    }
  }

  function renderAvailability() {
    const selected = selectedIds();
    const available = [];
    const unknown = [];
    const stale = [];
    const states = [];
    const endDate = dateTo.value || dateFrom.value;

    for (const location of locations) {
      if (!selected.has(location.location_id) || !coverMatches(location)) continue;
      if (location.snapshot_status === "no_data") {
        states.push([location, "Pas encore collecté"]);
        continue;
      }
      if (location.snapshot_status === "error" || location.snapshot_status === "unavailable") {
        states.push([location, "Données indisponibles"]);
        continue;
      }

      const matches = (location.slots || []).filter(matchesFilters);
      for (const slot of matches) {
        if (slot.status === "unavailable") continue;
        if (location.snapshot_status === "stale") stale.push({ location, slot });
        else if (slot.status === "unknown") unknown.push({ location, slot });
        else if (slot.status === "available") available.push({ location, slot });
      }

      if (location.window_end && endDate && endDate > location.window_end) {
        states.push([location, `Hors période publiée après le ${dateShortFormatter.format(new Date(`${location.window_end}T12:00:00Z`))}`]);
      } else if (location.snapshot_status === "success" && matches.length === 0) {
        states.push([location, "Aucun créneau ne correspond aux filtres sélectionnés"]);
      }
    }

    const availableResults = document.querySelector("#available-results");
    renderSlotGroups(availableResults, available, "available");
    if (available.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-results";
      empty.textContent = selected.size
        ? "Aucun créneau libre ne correspond aux filtres sélectionnés."
        : "Sélectionne au moins un club pour afficher les créneaux.";
      availableResults.append(empty);
    }
    renderSlotGroups(document.querySelector("#unknown-results"), unknown, "unknown");
    renderSlotGroups(document.querySelector("#stale-results"), stale, "stale");
    document.querySelector("#available-count").textContent = String(available.length);
    document.querySelector("#unknown-section").hidden = unknown.length === 0;
    document.querySelector("#stale-section").hidden = stale.length === 0;
    locationStatuses.replaceChildren();
    for (const [location, message] of states) {
      const item = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = location.canonical_name;
      const status = document.createElement("span");
      status.textContent = message;
      item.append(name, status);
      locationStatuses.append(item);
    }
    document.querySelector("#location-status-section").hidden = states.length === 0;
    document.querySelector("#result-summary").textContent = `${available.length} créneau${available.length === 1 ? "" : "x"} disponible${available.length === 1 ? "" : "s"}`;
  }

  function renderClubCount() {
    document.querySelector("#club-count").textContent = `${selectedIds().size}/${locations.length}`;
  }

  function showRefreshStatus(status) {
    const active = status.status === "queued" || status.status === "running";
    const finished = ["success", "partial", "error"].includes(status.status);
    const nextAllowed = status.next_allowed_at ? Date.parse(status.next_allowed_at) : 0;
    const cooling = !active && nextAllowed > Date.now();
    refreshButton.disabled = active || cooling;
    refreshButton.textContent = active ? "Actualisation…" : cooling ? "Patiente un peu" : "Actualiser";

    if (active) {
      refreshMessage.textContent = `Actualisation en cours · ${status.completed_locations || 0}/${status.total_locations || 23} clubs`;
    } else if (cooling) {
      refreshMessage.textContent = `Prochaine actualisation possible à ${formatDateTime(status.next_allowed_at)}`;
    } else if (status.finished_at) {
      const result = status.status === "success"
        ? "Mise à jour terminée"
        : status.status === "partial"
          ? "Mise à jour partielle"
          : "Échec de la mise à jour";
      refreshMessage.textContent = `${result} · ${formatDateTime(status.finished_at)}`;
    } else {
      refreshMessage.textContent = status.next_scheduled_at
        ? `Prochaine collecte · ${formatDateTime(status.next_scheduled_at)}`
        : "Disponibilités publiques mises en cache";
    }

    if (refreshTimer) window.clearTimeout(refreshTimer);
    if (active || cooling) {
      refreshTimer = window.setTimeout(loadRefreshStatus, active ? 2000 : 15000);
    } else {
      refreshTimer = window.setTimeout(loadRefreshStatus, 60000);
    }

    if (
      finished &&
      status.job_id &&
      status.finished_at &&
      Date.parse(status.finished_at) > availabilityGeneratedAt &&
      reloadedRefreshJobId !== status.job_id
    ) {
      reloadedRefreshJobId = status.job_id;
      void loadAvailability();
    }
  }

  async function loadRefreshStatus() {
    try {
      const response = await fetch("/api/refresh/status", { cache: "no-store" });
      if (response.ok) showRefreshStatus(await response.json());
    } catch {
      refreshMessage.textContent = "Statut d’actualisation indisponible";
    }
  }

  async function requestRefresh() {
    refreshButton.disabled = true;
    try {
      const response = await fetch("/api/refresh", { method: "POST" });
      const status = await response.json();
      showRefreshStatus(status);
    } catch {
      refreshButton.disabled = false;
      refreshMessage.textContent = "La demande d’actualisation a échoué.";
    }
  }

  async function loadAvailability() {
    try {
      const response = await fetch("/api/availability", { cache: "no-store" });
      if (!response.ok) throw new Error("availability request failed");
      const payload = await response.json();
      availabilityGeneratedAt = Date.parse(payload.generated_at) || availabilityGeneratedAt;
      locations = Object.values(payload.locations || {});
      const ids = locations.map((location) => location.location_id);
      selectedLocationIds = savedIds(ids);
      dateFrom.value = today();
      dateTo.value = shiftDate(dateFrom.value, 14);
      renderClubList();
      renderAvailability();
      document.querySelector("#load-error").hidden = true;
      const latest = locations
        .map((location) => location.last_success_at)
        .filter(Boolean)
        .sort()
        .at(-1);
      if (latest) refreshMessage.textContent = `Dernière donnée fiable · ${formatDateTime(latest)}`;

      try {
        if (localStorage.getItem(storageKey) === null) {
          localStorage.setItem(storageKey, JSON.stringify([...selectedLocationIds]));
        }
      } catch {
        // Filtering still works when browser storage is disabled.
      }
      await loadRefreshStatus();
    } catch {
      document.querySelector("#load-error").hidden = false;
      document.querySelector("#result-summary").textContent = "Disponibilités indisponibles";
    }
  }

  function saveSelection(event) {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    if (input.checked) selectedLocationIds.add(input.value);
    else selectedLocationIds.delete(input.value);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...selectedIds()]));
    } catch {
      // The current selection remains active for this page view.
    }
    renderClubCount();
    renderAvailability();
  }

  document.querySelector("#evening-preset").addEventListener("click", () => {
    const value = today();
    dateFrom.value = value;
    dateTo.value = value;
    timeFrom.value = "18:00";
    timeTo.value = "22:00";
    renderAvailability();
  });
  document.querySelector("#reset-dates").addEventListener("click", () => {
    dateFrom.value = today();
    dateTo.value = shiftDate(dateFrom.value, 14);
    timeFrom.value = "";
    timeTo.value = "";
    renderAvailability();
  });
  for (const input of [dateFrom, dateTo, timeFrom, timeTo]) {
    input.addEventListener("change", renderAvailability);
  }
  document.querySelectorAll("input[name=cover]").forEach((input) => {
    input.addEventListener("change", renderAvailability);
  });
  clubList.addEventListener("change", saveSelection);
  clubSearch.addEventListener("input", renderClubList);
  refreshButton.addEventListener("click", requestRefresh);
  const filterPanel = document.querySelector("#filter-panel");
  const desktopFilters = window.matchMedia("(min-width: 768px)");
  const updateFilterPanel = (event) => {
    filterPanel.open = event.matches;
  };
  desktopFilters.addEventListener("change", updateFilterPanel);
  updateFilterPanel(desktopFilters);
  loadAvailability();
})();
