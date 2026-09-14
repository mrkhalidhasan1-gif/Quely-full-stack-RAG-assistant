const API_URL = "http://localhost:5001";

let currentDocumentPath = null;
let currentDocumentName = null;
let isGuestMode = false;


// =========================
// PAGE CONTROLS
// =========================

function showAuth(type) {
    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("guestPage").classList.add("hidden");
    document.getElementById("dashboardPage").classList.add("hidden");
    document.getElementById("authPage").classList.remove("hidden");
    document.querySelector(".header").classList.remove("hidden");
    document.querySelector(".footer").classList.remove("hidden");

    document.getElementById("loginForm").classList.add("hidden");
    document.getElementById("signupForm").classList.add("hidden");
    document.getElementById("authMessage").textContent = "";

    if (type === "login") {
        document.getElementById("loginForm").classList.remove("hidden");
    } else {
        document.getElementById("signupForm").classList.remove("hidden");
    }
}


function showLanding() {
    isGuestMode = false;
    currentDocumentPath = null;
    currentDocumentName = null;

    document.getElementById("authPage").classList.add("hidden");
    document.getElementById("dashboardPage").classList.add("hidden");
    document.getElementById("guestPage").classList.add("hidden");
    document.getElementById("landingPage").classList.remove("hidden");

    document.querySelector(".header").classList.remove("hidden");
    document.querySelector(".footer").classList.remove("hidden");
}


// =========================
// SIGNUP
// =========================

async function signup(event) {
    event.preventDefault();

    const name = document.getElementById("signupName").value;
    const email = document.getElementById("signupEmail").value;
    const password = document.getElementById("signupPassword").value;
    const message = document.getElementById("authMessage");

    message.textContent = "Creating your account...";

    try {
        const response = await fetch(`${API_URL}/api/auth/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            message.textContent = data.message || "Signup failed.";
            return;
        }

        message.textContent = "Account created! You can now log in.";

        document.getElementById("signupForm").classList.add("hidden");
        document.getElementById("loginForm").classList.remove("hidden");
        document.getElementById("loginEmail").value = email;
    } catch (error) {
        console.error(error);
        message.textContent = "Unable to connect to Quely server.";
    }
}


// =========================
// LOGIN
// =========================

async function login(event) {
    event.preventDefault();

    const email = document.getElementById("loginEmail").value;
    const password = document.getElementById("loginPassword").value;
    const message = document.getElementById("authMessage");

    message.textContent = "Logging in...";

    try {
        const response = await fetch(`${API_URL}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            message.textContent = data.message || "Login failed.";
            return;
        }

        localStorage.setItem("quelyToken", data.token);
        localStorage.setItem("quelyUser", JSON.stringify(data.user));
        message.textContent = "Login successful!";

        setTimeout(() => {
            openDashboard(data.user, false);
        }, 300);
    } catch (error) {
        console.error(error);
        message.textContent = "Unable to connect to Quely server.";
    }
}


// =========================
// GUEST MODE
// =========================

function showGuestMode() {
    isGuestMode = true;
    currentDocumentPath = null;
    currentDocumentName = null;

    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("authPage").classList.add("hidden");
    document.getElementById("dashboardPage").classList.add("hidden");

    document.querySelector(".header").classList.remove("hidden");
    document.querySelector(".footer").classList.remove("hidden");

    document.getElementById("guestPage").classList.remove("hidden");
    document.getElementById("guestMessage").textContent = "";
}


// =========================
// GUEST SOURCE
// =========================

async function processGuestSource() {
    const file = document.getElementById("guestFile").files[0];
    const url = document.getElementById("guestUrl").value.trim();
    const message = document.getElementById("guestMessage");

    if (!file && !url) {
        message.textContent = "Please upload a document or enter a website URL.";
        return;
    }

    if (file && url) {
        message.textContent = "Please choose either a document or a website.";
        return;
    }

    message.textContent = "Processing your source...";

    try {
        let response;
        let data;

        if (url) {
            response = await fetch(`${API_URL}/api/documents/guest-website`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url })
            });

            data = await response.json();

            if (!response.ok) {
                message.textContent = data.message || "Website processing failed.";
                return;
            }

            currentDocumentPath = data.documentPath;
            currentDocumentName = data.documentName || "Website";

            showGuestWorkspace(currentDocumentName);
            return;
        }

        const formData = new FormData();
        formData.append("document", file);

        response = await fetch(`${API_URL}/api/documents/guest-upload`, {
            method: "POST",
            body: formData
        });

        data = await response.json();

        if (!response.ok) {
            message.textContent = data.message || "Upload failed.";
            return;
        }

        currentDocumentPath = data.file.path;
        currentDocumentName = file.name;

        showGuestWorkspace(currentDocumentName);
    } catch (error) {
        console.error(error);
        message.textContent = "Unable to connect to Quely server.";
    }
}


// =========================
// GUEST WORKSPACE
// =========================

function showGuestWorkspace(documentName) {
    isGuestMode = true;

    document.getElementById("guestPage").classList.add("hidden");
    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("authPage").classList.add("hidden");

    document.querySelector(".header").classList.add("hidden");
    document.querySelector(".footer").classList.add("hidden");

    document.getElementById("dashboardPage").classList.remove("hidden");

    document.getElementById("dashboardUserName").textContent = "Guest";
    document.getElementById("dashboardUserEmail").textContent = "Temporary session";
    document.querySelector(".user-avatar").textContent = "G";
    document.querySelector(".logout-btn").classList.add("hidden");

    document.getElementById("chatHistory").innerHTML = `
        <p class="empty-history">Guest conversations are temporary.</p>
    `;

    document.getElementById("activeDocumentName").textContent = documentName;

    showChatContainer();
    resetChatMessages();
}


// =========================
// DASHBOARD
// =========================

function openDashboard(user, restoreLatestChat = false) {
    isGuestMode = false;

    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("authPage").classList.add("hidden");
    document.getElementById("guestPage").classList.add("hidden");

    document.querySelector(".header").classList.add("hidden");
    document.querySelector(".footer").classList.add("hidden");

    document.getElementById("dashboardPage").classList.remove("hidden");
    document.querySelector(".logout-btn").classList.remove("hidden");

    document.getElementById("dashboardUserName").textContent = user.name;
    document.getElementById("dashboardUserEmail").textContent = user.email;
    document.querySelector(".user-avatar").textContent = user.name.charAt(0).toUpperCase();

    if (restoreLatestChat) {
        loadChatHistory(true);
    } else {
        loadChatHistory(false);
        startNewChat(false);
    }
}


// =========================
// NEW CHAT
// =========================

function startNewChat(showStatus = true) {
    currentDocumentPath = null;
    currentDocumentName = null;

    const chatContainer = document.getElementById("chatContainer");
    const sourceOptions = document.querySelector(".source-options");
    const dashboardContent = document.querySelector(".dashboard-content");

    chatContainer.classList.add("hidden");
    sourceOptions.classList.remove("hidden");

    document.getElementById("dashboardStatus").textContent = "";

    const fileInput = document.getElementById("dashboardFile");
    if (fileInput) fileInput.value = "";

    const urlInput = document.getElementById("dashboardUrl");
    if (urlInput) urlInput.value = "";

    resetChatMessages();

    document.getElementById("chatInput").value = "";
    document.getElementById("activeDocumentName").textContent = "No source selected";

    if (showStatus) {
        document.getElementById("dashboardStatus").textContent = "Start a new chat by uploading a source.";
    }

    if (dashboardContent) dashboardContent.scrollTop = 0;
}


// =========================
// SHOW CHAT
// =========================

function showChatContainer() {
    document.querySelector(".source-options").classList.add("hidden");
    document.getElementById("chatContainer").classList.remove("hidden");
}


// =========================
// RESET CHAT
// =========================

function resetChatMessages() {
    const container = document.getElementById("chatMessages");

    container.innerHTML = `
        <div class="ai-message message-enter">
            <div class="message-avatar">✦</div>
            <div class="message-content">
                <span class="message-label">Quely AI</span>
                <p>I've analyzed your document. Ask me anything about it and I'll find the relevant information.</p>
            </div>
        </div>
    `;
}


// =========================
// LOGOUT
// =========================

function logout() {
    localStorage.removeItem("quelyToken");
    localStorage.removeItem("quelyUser");
    location.reload();
}


// =========================
// DASHBOARD BACK
// =========================

function dashboardBack() {
    if (isGuestMode) {
        showLanding();
        return;
    }

    const confirmLogout = confirm("Going back will log you out. Are you sure?");

    if (confirmLogout) logout();
}


// =========================
// UPLOAD DOCUMENT
// =========================

async function uploadDocument() {
    const fileInput = document.getElementById("dashboardFile");
    const file = fileInput.files[0];
    const status = document.getElementById("dashboardStatus");

    if (!file) {
        status.textContent = "Please choose a file first.";
        return;
    }

    const formData = new FormData();
    formData.append("document", file);

    status.textContent = "Uploading and processing...";

    try {
        const token = localStorage.getItem("quelyToken");

        const response = await fetch(`${API_URL}/api/documents/upload`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`
            },
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            status.textContent = data.message || "Upload failed.";
            return;
        }

        currentDocumentPath = data.file.path;
        currentDocumentName = file.name;

        status.textContent = "File processed successfully.";

        document.getElementById("activeDocumentName").textContent = file.name;

        showChatContainer();
        resetChatMessages();
    } catch (error) {
        console.error(error);
        status.textContent = "Unable to connect to Quely server.";
    }
}


// =========================
// ADD WEBSITE
// =========================

async function addWebsite() {
    const urlInput = document.getElementById("dashboardUrl");
    const status = document.getElementById("dashboardStatus");
    const url = urlInput.value.trim();

    if (!url) {
        status.textContent = "Please enter a website URL.";
        return;
    }

    status.textContent = "Fetching and processing website...";

    try {
        const token = localStorage.getItem("quelyToken");

        const response = await fetch(`${API_URL}/api/documents/website`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (!response.ok) {
            status.textContent = data.message || "Website processing failed.";
            return;
        }

        currentDocumentPath = data.documentPath;
        currentDocumentName = data.documentName || "Website";

        status.textContent = "Website processed successfully.";
        document.getElementById("activeDocumentName").textContent = currentDocumentName;

        showChatContainer();
        resetChatMessages();
    } catch (error) {
        console.error(error);
        status.textContent = "Unable to connect to Quely server.";
    }
}


// =========================
// AI CHAT
// =========================

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const question = input.value.trim();

    if (!question) return;

    if (!currentDocumentPath) {
        addAIMessage("Please upload a document or add a website first.");
        return;
    }

    addUserMessage(question);
    input.value = "";

    const sendButton = document.getElementById("sendChatBtn");
    sendButton.disabled = true;

    document.getElementById("typingIndicator").classList.remove("hidden");

    try {
        let endpoint;
        let headers = { "Content-Type": "application/json" };

        if (isGuestMode) {
            endpoint = `${API_URL}/api/documents/guest-ask`;
        } else {
            endpoint = `${API_URL}/api/documents/ask`;
            headers.Authorization = `Bearer ${localStorage.getItem("quelyToken")}`;
        }

        const response = await fetch(endpoint, {
            method: "POST",
            headers,
            body: JSON.stringify({
                documentPath: currentDocumentPath,
                documentName: currentDocumentName,
                question
            })
        });

        const data = await response.json();

        if (!response.ok) {
            addAIMessage(data.message || "Sorry, I couldn't answer that.");
            return;
        }

        addAIMessage(data.answer, data.sources);

        if (!isGuestMode) loadChatHistory(false);
    } catch (error) {
        console.error(error);
        addAIMessage("Unable to connect to Quely.");
    } finally {
        document.getElementById("typingIndicator").classList.add("hidden");
        sendButton.disabled = false;
        input.focus();
    }
}


// =========================
// USER MESSAGE
// =========================

function addUserMessage(message) {
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");

    div.className = "user-message";

    div.innerHTML = `
        <div class="message-avatar">👤</div>
        <div class="message-content">
            <span class="message-label">You</span>
            <p></p>
        </div>
    `;

    div.querySelector("p").textContent = message;

    container.appendChild(div);
    scrollChatToBottom();
}


// =========================
// AI MESSAGE
// =========================

function addAIMessage(message, sources = []) {
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");

    div.className = "ai-message";

    div.innerHTML = `
        <div class="message-avatar">✦</div>
        <div class="message-content">
            <span class="message-label">Quely AI</span>
            <p></p>
            <div class="source-list"></div>
        </div>
    `;

    div.querySelector("p").textContent = message;

    const sourceList = div.querySelector(".source-list");

    if (sources && sources.length > 0) {
        sources.slice(0, 3).forEach(source => {
            const sourceChip = document.createElement("span");

            sourceChip.className = "source-chip";
            sourceChip.textContent = source.page ? `Page ${source.page}` : "Source";

            sourceList.appendChild(sourceChip);
        });
    }

    container.appendChild(div);
    scrollChatToBottom();
}


// =========================
// ENTER TO SEND
// =========================

function handleChatKey(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}


// =========================
// SCROLL
// =========================

function scrollChatToBottom() {
    const container = document.getElementById("chatMessages");
    container.scrollTop = container.scrollHeight;
}


// =========================
// LOAD CHAT HISTORY
// =========================

async function loadChatHistory(restoreLatestChat = false) {
    const token = localStorage.getItem("quelyToken");
    if (!token) return;

    try {
        const response = await fetch(`${API_URL}/api/chats/history`, {
            method: "GET",
            headers: { "Authorization": `Bearer ${token}` }
        });

        const data = await response.json();

        if (!response.ok) {
            console.error("History error:", data.message);
            return;
        }

        const historyContainer = document.getElementById("chatHistory");
        historyContainer.innerHTML = "";

        if (!data.chats || data.chats.length === 0) {
            historyContainer.innerHTML = `<p class="empty-history">No conversations yet.</p>`;
            return;
        }

        data.chats.forEach(chat => {
            const chatItem = document.createElement("div");
            chatItem.className = "history-item";

            const date = new Date(chat.createdAt).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric"
            });

            const isWebsite = chat.documentName && !chat.documentName.match(/\.(pdf|docx|txt)$/i);
            const icon = isWebsite ? "🌐" : "📄";

            chatItem.innerHTML = `
                <div class="history-item-title">${icon} ${escapeHtml(chat.documentName || "Document")}</div>
                <div class="history-item-date">${date}</div>
            `;

            chatItem.onclick = () => openChatFromHistory(chat);
            historyContainer.appendChild(chatItem);
        });

        if (restoreLatestChat && data.chats.length > 0) {
            openChatFromHistory(data.chats[0]);
        }
    } catch (error) {
        console.error("Unable to load chat history:", error);
    }
}


// =========================
// OPEN OLD CHAT
// =========================

async function openChatFromHistory(chat) {
    isGuestMode = false;
    currentDocumentPath = chat.documentPath;
    currentDocumentName = chat.documentName || "Document";

    try {
        const token = localStorage.getItem("quelyToken");

        await fetch(`${API_URL}/api/chats/open/${chat._id}`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${token}` }
        });

        loadChatHistory(false);
    } catch (error) {
        console.error("Unable to update chat activity:", error);
    }

    document.querySelector(".source-options").classList.add("hidden");
    document.getElementById("chatContainer").classList.remove("hidden");
    document.getElementById("activeDocumentName").textContent = currentDocumentName;

    const messagesContainer = document.getElementById("chatMessages");
    messagesContainer.innerHTML = "";

    chat.messages.forEach(message => {
        if (message.role === "user") addUserMessage(message.content);
        else addAIMessage(message.content, message.sources || []);
    });

    scrollChatToBottom();
}


// =========================
// ESCAPE HTML
// =========================

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
}


// =========================
// RESTORE LOGIN ON REFRESH
// =========================

document.addEventListener("DOMContentLoaded", () => {
    const token = localStorage.getItem("quelyToken");
    const userData = localStorage.getItem("quelyUser");

    if (token && userData) {
        try {
            const user = JSON.parse(userData);
            openDashboard(user, true);
        } catch (error) {
            console.error("Invalid saved user:", error);

            localStorage.removeItem("quelyToken");
            localStorage.removeItem("quelyUser");
        }
    }
});