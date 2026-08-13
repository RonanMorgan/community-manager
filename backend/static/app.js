// Vanilla JS — no build step needed, keeps the docker-compose setup to a
// single backend container serving both the API and the HTML pages.

function openModal(id) {
    document.getElementById(id).classList.remove("hidden");
}
function closeModal(id) {
    document.getElementById(id).classList.add("hidden");
}

document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
});

async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!response.ok) {
        let detail = `Erreur ${response.status}`;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch (_) {
            // ignore non-JSON error bodies
        }
        throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
}

// --- Inline rename of a resource ---
document.querySelectorAll(".resource-name-input").forEach((input) => {
    let originalValue = input.value;

    input.addEventListener("focus", () => {
        originalValue = input.value;
    });

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            input.blur();
        } else if (e.key === "Escape") {
            input.value = originalValue;
            input.blur();
        }
    });

    input.addEventListener("blur", async () => {
        const newValue = input.value.trim();
        if (!newValue || newValue === originalValue) {
            input.value = originalValue;
            return;
        }
        const resourceId = input.dataset.resourceId;
        input.disabled = true;
        try {
            await apiFetch(`/api/group-resources/${resourceId}`, {
                method: "PATCH",
                body: JSON.stringify({ display_name: newValue }),
            });
            originalValue = newValue;
            const viewBtn = input.closest(".resource-cell").querySelector(".btn-view-users");
            if (viewBtn) viewBtn.dataset.groupName = newValue;
        } catch (err) {
            alert(`Le renommage a échoué : ${err.message}`);
            input.value = originalValue;
        } finally {
            input.disabled = false;
        }
    });
});

// --- Collapsible sections (Projets / Pôles / Antennes / Non catégorisés) ---
const SECTION_COLLAPSE_STORAGE_PREFIX = "community-manager:section-collapsed:";

document.querySelectorAll(".section-toggle").forEach((toggle) => {
    const slug = toggle.dataset.sectionSlug;
    const section = toggle.closest(".category-section");
    const storageKey = SECTION_COLLAPSE_STORAGE_PREFIX + slug;

    if (localStorage.getItem(storageKey) === "1") {
        section.classList.add("collapsed");
    }

    toggle.addEventListener("click", () => {
        const collapsed = section.classList.toggle("collapsed");
        localStorage.setItem(storageKey, collapsed ? "1" : "0");
    });
});

// --- Reattach a resource to a different collection/channel (search combobox) ---
function debounce(fn, delayMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delayMs);
    };
}

document.querySelectorAll(".btn-relink").forEach((btn) => {
    const resourceId = btn.dataset.resourceId;
    const combobox = document.querySelector(`.relink-combobox[data-resource-id="${resourceId}"]`);
    if (!combobox) return;
    const input = combobox.querySelector(".relink-search-input");
    const resultsList = combobox.querySelector(".relink-results");

    btn.addEventListener("click", () => {
        // Close any other open combobox before opening this one.
        document.querySelectorAll(".relink-combobox").forEach((el) => {
            if (el !== combobox) el.classList.add("hidden");
        });
        combobox.classList.toggle("hidden");
        if (!combobox.classList.contains("hidden")) {
            input.value = "";
            resultsList.innerHTML = "";
            input.focus();
        }
    });

    const runSearch = debounce(async (query) => {
        if (query.trim().length < 3) {
            resultsList.innerHTML = `<li class="relink-empty">Tapez au moins 3 caractères...</li>`;
            return;
        }
        resultsList.innerHTML = `<li class="relink-empty">Recherche...</li>`;
        try {
            const candidates = await apiFetch(
                `/api/group-resources/${resourceId}/search-candidates?q=${encodeURIComponent(query)}`
            );
            if (candidates.length === 0) {
                resultsList.innerHTML = `<li class="relink-empty">Aucun résultat.</li>`;
                return;
            }
            resultsList.innerHTML = "";
            candidates.forEach((c) => {
                const li = document.createElement("li");
                li.textContent = c.name;
                li.addEventListener("click", async () => {
                    try {
                        await apiFetch(`/api/group-resources/${resourceId}/relink`, {
                            method: "POST",
                            body: JSON.stringify({ external_id: c.id, display_name: c.name }),
                        });
                        window.location.reload();
                    } catch (err) {
                        resultsList.innerHTML = `<li class="relink-empty">Échec : ${err.message}</li>`;
                    }
                });
                resultsList.appendChild(li);
            });
        } catch (err) {
            resultsList.innerHTML = `<li class="relink-empty">Erreur : ${err.message}</li>`;
        }
    }, 300);

    input.addEventListener("input", () => runSearch(input.value));
});

// --- Sync from Authentik ---
const btnSync = document.getElementById("btn-sync");
if (btnSync) {
    const originalSyncLabel = btnSync.textContent;

    btnSync.addEventListener("click", async () => {
        const feedback = document.getElementById("sync-feedback");
        feedback.classList.remove("hidden", "alert-error", "alert-success");
        feedback.textContent = "Synchronisation en cours...";
        btnSync.disabled = true;
        btnSync.classList.add("btn-syncing");
        btnSync.textContent = "↻ Synchronisation en cours...";

        try {
            const result = await apiFetch("/api/sync", { method: "POST" });
            const parts = [
                `${result.groups_created} groupe(s) créé(s)`,
                `${result.groups_updated} groupe(s) déjà connu(s)`,
            ];
            if (result.groups_deleted > 0) {
                parts.push(`${result.groups_deleted} groupe(s) supprimé(s) (absents d'Authentik)`);
            }
            parts.push(`${result.resources_matched} ressource(s) trouvée(s)`, `${result.resources_not_found} sans correspondance`);
            if (result.warnings && result.warnings.length > 0) {
                parts.push(`${result.warnings.length} avertissement(s)`);
            }
            if (result.errors.length > 0) {
                parts.push(`${result.errors.length} erreur(s)`);
                feedback.classList.add("alert-error");
            } else {
                feedback.classList.add("alert-success");
            }
            feedback.textContent = `Synchronisation terminée : ${parts.join(", ")}.`;
            setTimeout(() => window.location.reload(), 1200);
        } catch (err) {
            feedback.classList.add("alert-error");
            feedback.textContent = `Échec de la synchronisation : ${err.message}`;
            btnSync.disabled = false;
            btnSync.classList.remove("btn-syncing");
            btnSync.textContent = originalSyncLabel;
        }
    });
}

// --- Manual category assignment (uncategorized groups) ---
document.querySelectorAll(".category-select").forEach((select) => {
    select.addEventListener("change", async () => {
        const groupId = select.dataset.groupId;
        const category = select.value;
        select.disabled = true;
        try {
            await apiFetch(`/api/groups/${groupId}/category`, {
                method: "PATCH",
                body: JSON.stringify({ category }),
            });
            window.location.reload();
        } catch (err) {
            alert(`Impossible d'assigner la catégorie : ${err.message}`);
            select.disabled = false;
        }
    });
});

// --- Create group modal ---
const btnOpenCreateGroup = document.getElementById("btn-open-create-group");
if (btnOpenCreateGroup) {
    btnOpenCreateGroup.addEventListener("click", () => {
        document.getElementById("create-group-error").textContent = "";
        document.getElementById("form-create-group").reset();
        openModal("modal-create-group");
    });
}

const formCreateGroup = document.getElementById("form-create-group");
if (formCreateGroup) {
    formCreateGroup.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("create-group-error");
        errorEl.textContent = "";

        const formData = new FormData(formCreateGroup);
        const name = formData.get("name");
        const tools = formData.getAll("tools");

        try {
            await apiFetch("/api/groups", {
                method: "POST",
                body: JSON.stringify({ name, tools }),
            });
            window.location.reload();
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });
}

// --- Resource users modal ---
let currentResourceId = null;
let currentTool = null;

async function loadResourceUsers(resourceId) {
    const tbody = document.getElementById("resource-users-tbody");
    const errorEl = document.getElementById("resource-users-error");
    errorEl.textContent = "";
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Chargement...</td></tr>`;

    try {
        const users = await apiFetch(`/api/group-resources/${resourceId}/users`);
        if (users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Aucun utilisateur.</td></tr>`;
            return;
        }
        tbody.innerHTML = "";
        const canRemove = currentTool === "outline";
        users.forEach((u) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${escapeHtml(u.name || "—")}</td>
                <td>${escapeHtml(u.email || "—")}</td>
                <td>${u.permission === "read_write" || u.permission === "admin" ? "Lecture / écriture" : "Lecture"}</td>
                <td>${canRemove ? `<button class="btn-link btn-remove-user" data-user-id="${u.id}">Retirer</button>` : ""}</td>
            `;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll(".btn-remove-user").forEach((btn) => {
            btn.addEventListener("click", async () => {
                if (!confirm("Retirer cet utilisateur de la ressource ?")) return;
                try {
                    await apiFetch(`/api/group-resources/${currentResourceId}/users/${btn.dataset.userId}`, {
                        method: "DELETE",
                    });
                    loadResourceUsers(currentResourceId);
                } catch (err) {
                    errorEl.textContent = err.message;
                }
            });
        });
    } catch (err) {
        tbody.innerHTML = "";
        errorEl.textContent = err.message;
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

document.querySelectorAll(".btn-view-users").forEach((btn) => {
    btn.addEventListener("click", () => {
        currentResourceId = btn.dataset.resourceId;
        currentTool = btn.dataset.tool;
        document.getElementById("resource-users-title").textContent =
            `Utilisateurs — ${btn.dataset.groupName} (${btn.dataset.tool})`;
        document.getElementById("form-add-user").reset();

        const addSection = document.getElementById("add-user-section");
        const unsupportedNote = document.getElementById("add-user-unsupported-note");
        if (currentTool === "outline") {
            addSection.classList.remove("hidden");
            unsupportedNote.classList.add("hidden");
        } else {
            addSection.classList.add("hidden");
            unsupportedNote.classList.remove("hidden");
        }

        openModal("modal-resource-users");
        loadResourceUsers(currentResourceId);
    });
});

const formAddUser = document.getElementById("form-add-user");
if (formAddUser) {
    formAddUser.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("resource-users-error");
        errorEl.textContent = "";

        const email = document.getElementById("add-user-email").value;
        const permission = document.getElementById("add-user-permission").value;

        try {
            await apiFetch(`/api/group-resources/${currentResourceId}/users`, {
                method: "POST",
                body: JSON.stringify({ email, permission }),
            });
            formAddUser.reset();
            loadResourceUsers(currentResourceId);
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });
}
