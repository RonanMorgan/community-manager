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

// --- Sync from Authentik ---
const btnSync = document.getElementById("btn-sync");
if (btnSync) {
    btnSync.addEventListener("click", async () => {
        const feedback = document.getElementById("sync-feedback");
        feedback.classList.remove("hidden", "alert-error", "alert-success");
        feedback.textContent = "Synchronisation en cours...";
        btnSync.disabled = true;

        try {
            const result = await apiFetch("/api/sync", { method: "POST" });
            const parts = [
                `${result.groups_created} groupe(s) créé(s)`,
                `${result.groups_updated} groupe(s) déjà connu(s)`,
                `${result.resources_matched} ressource(s) trouvée(s)`,
                `${result.resources_not_found} sans correspondance`,
            ];
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
        }
    });
}

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
