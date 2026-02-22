function showAdminError(msg) {
    const el = document.getElementById('adminError');
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearAdminError() {
    const el = document.getElementById('adminError');
    el.textContent = '';
    el.classList.add('hidden');
}

async function loadUsers() {
    clearAdminError();
    const response = await fetch('/v1/admin/users');
    if (response.status === 401) {
        window.location.href = '/login';
        return;
    }
    if (response.status === 403) {
        showAdminError('Access denied. Admin privileges required.');
        return;
    }
    if (!response.ok) {
        showAdminError('Failed to load users. Please refresh the page.');
        return;
    }
    const data = await response.json();
    renderUsers(data.users);
}

function renderUsers(users) {
    const tbody = document.getElementById('userTableBody');
    tbody.innerHTML = '';
    for (const u of users) {
        const tr = document.createElement('tr');
        tr.dataset.userId = u.id;

        const nameTd = document.createElement('td');
        nameTd.textContent = u.username;
        tr.appendChild(nameTd);

        const statusTd = document.createElement('td');
        statusTd.textContent = u.status;
        statusTd.className = `status-${u.status}`;
        tr.appendChild(statusTd);

        const deactivatedTd = document.createElement('td');
        deactivatedTd.textContent = u.deactivated_at
            ? new Date(u.deactivated_at).toLocaleString()
            : '—';
        tr.appendChild(deactivatedTd);

        const actionTd = document.createElement('td');
        if (u.status === 'active') {
            const btn = document.createElement('button');
            btn.textContent = 'Deactivate';
            btn.className = 'deactivate-btn';
            btn.onclick = () => deactivateUser(u.id);
            actionTd.appendChild(btn);
        } else if (u.status === 'deactivated') {
            const btn = document.createElement('button');
            btn.textContent = 'Reactivate';
            btn.className = 'reactivate-btn';
            btn.onclick = () => reactivateUser(u.id);
            actionTd.appendChild(btn);
        }
        tr.appendChild(actionTd);

        tbody.appendChild(tr);
    }
}

async function deactivateUser(userId) {
    clearAdminError();
    const response = await fetch(`/v1/users/${userId}/deactivate`, { method: 'POST' });
    if (response.status === 401) {
        window.location.href = '/login';
        return;
    }
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showAdminError(data.error || 'Failed to deactivate user.');
        return;
    }
    await loadUsers();
}

async function reactivateUser(userId) {
    clearAdminError();
    const response = await fetch(`/v1/users/${userId}/reactivate`, { method: 'POST' });
    if (response.status === 401) {
        window.location.href = '/login';
        return;
    }
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showAdminError(data.error || 'Failed to reactivate user.');
        return;
    }
    await loadUsers();
}

async function adminInit() {
    await setUserHeader();
    await loadUsers();
}
