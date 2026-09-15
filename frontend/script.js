const LOCAL = ["localhost","127.0.0.1"].includes(window.location.hostname);
const API_URL = LOCAL ? "http://localhost:5001" : "";
const RAG_URL = LOCAL ? "http://localhost:8000" : "";

let currentDocumentId = null;
let currentDocumentName = null;
let isGuestMode = false;

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
    document.getElementById(type === "login" ? "loginForm" : "signupForm").classList.remove("hidden");
}

function showLanding() {
    isGuestMode = false;
    currentDocumentId = null;
    currentDocumentName = null;
    document.getElementById("authPage").classList.add("hidden");
    document.getElementById("dashboardPage").classList.add("hidden");
    document.getElementById("guestPage").classList.add("hidden");
    document.getElementById("landingPage").classList.remove("hidden");
    document.querySelector(".header").classList.remove("hidden");
    document.querySelector(".footer").classList.remove("hidden");
}

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
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({name,email,password})
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

async function login(event) {
    event.preventDefault();
    const email = document.getElementById("loginEmail").value;
    const password = document.getElementById("loginPassword").value;
    const message = document.getElementById("authMessage");
    message.textContent = "Logging in...";

    try {
        const response = await fetch(`${API_URL}/api/auth/login`, {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({email,password})
        });
        const data = await response.json();

        if (!response.ok) {
            message.textContent = data.message || "Login failed.";
            return;
        }

        localStorage.setItem("quelyToken", data.token);
        localStorage.setItem("quelyUser", JSON.stringify(data.user));
        message.textContent = "Login successful!";

        setTimeout(() => openDashboard(data.user, false), 300);
    } catch (error) {
        console.error(error);
        message.textContent = "Unable to connect to Quely server.";
    }
}

function showGuestMode() {
    isGuestMode = true;
    currentDocumentId = null;
    currentDocumentName = null;
    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("authPage").classList.add("hidden");
    document.getElementById("dashboardPage").classList.add("hidden");
    document.querySelector(".header").classList.remove("hidden");
    document.querySelector(".footer").classList.remove("hidden");
    document.getElementById("guestPage").classList.remove("hidden");
    document.getElementById("guestMessage").textContent = "";
}

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

    if (file && file.size > 4 * 1024 * 1024) {
        message.textContent = "File size must be under 4 MB.";
        return;
    }

    message.textContent = "Processing your source...";

    try {
        let response;
        let data;

        if (url) {
            response = await fetch(`${RAG_URL}/api/rag/guest-website`, {
                method: "POST",
                headers: {"Content-Type":"application/json"},
                body: JSON.stringify({url})
            });
        } else {
            const formData = new FormData();
            formData.append("document", file);
            response = await fetch(`${RAG_URL}/api/rag/guest-upload`, {
                method: "POST",
                body: formData
            });
        }

        data = await response.json();

        if (!response.ok) {
            message.textContent = data.message || "Source processing failed.";
            return;
        }

        currentDocumentId = data.documentId;
        currentDocumentName = data.documentName || (file ? file.name : "Website");
        showGuestWorkspace(currentDocumentName);
    } catch (error) {
        console.error(error);
        message.textContent = "Unable to connect to Quely.";
    }
}

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
    document.getElementById("chatHistory").innerHTML = `<p class="empty-history">Guest conversations are temporary.</p>`;
    document.getElementById("activeDocumentName").textContent = documentName;
    showChatContainer();
    resetChatMessages();
}

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

    if (restoreLatestChat) loadChatHistory(true);
    else {
        loadChatHistory(false);
        startNewChat(false);
    }
}

function startNewChat(showStatus = true) {
    currentDocumentId = null;
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

    if (showStatus) document.getElementById("dashboardStatus").textContent = "Start a new chat by uploading a source.";
    if (dashboardContent) dashboardContent.scrollTop = 0;
}

function showChatContainer() {
    document.querySelector(".source-options").classList.add("hidden");
    document.getElementById("chatContainer").classList.remove("hidden");
}

function resetChatMessages() {
    document.getElementById("chatMessages").innerHTML = `
        <div class="ai-message message-enter">
            <div class="message-avatar">✦</div>
            <div class="message-content">
                <span class="message-label">Quely AI</span>
                <p>I've analyzed your document. Ask me anything about it and I'll find the relevant information.</p>
            </div>
        </div>
    `;
}

function logout() {
    localStorage.removeItem("quelyToken");
    localStorage.removeItem("quelyUser");
    location.reload();
}

function dashboardBack() {
    if (isGuestMode) {
        showLanding();
        return;
    }

    if (confirm("Going back will log you out. Are you sure?")) logout();
}

async function uploadDocument() {
    const fileInput = document.getElementById("dashboardFile");
    const file = fileInput.files[0];
    const status = document.getElementById("dashboardStatus");

    if (!file) {
        status.textContent = "Please choose a file first.";
        return;
    }

    if (file.size > 4 * 1024 * 1024) {
        status.textContent = "File size must be under 4 MB.";
        return;
    }

    status.textContent = "Uploading and processing...";

    try {
        const formData = new FormData();
        formData.append("document", file);

        const response = await fetch(`${RAG_URL}/api/rag/upload`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${localStorage.getItem("quelyToken")}`
            },
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            status.textContent = data.message || "Upload failed.";
            return;
        }

        currentDocumentId = data.documentId;
        currentDocumentName = data.documentName || file.name;

        status.textContent = "File processed successfully.";
        document.getElementById("activeDocumentName").textContent = currentDocumentName;
        showChatContainer();
        resetChatMessages();
    } catch (error) {
        console.error(error);
        status.textContent = "Unable to connect to Quely.";
    }
}

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
        const response = await fetch(`${RAG_URL}/api/rag/website`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("quelyToken")}`
            },
            body: JSON.stringify({url})
        });

        const data = await response.json();

        if (!response.ok) {
            status.textContent = data.message || "Website processing failed.";
            return;
        }

        currentDocumentId = data.documentId;
        currentDocumentName = data.documentName || "Website";

        status.textContent = "Website processed successfully.";
        document.getElementById("activeDocumentName").textContent = currentDocumentName;
        showChatContainer();
        resetChatMessages();
    } catch (error) {
        console.error(error);
        status.textContent = "Unable to connect to Quely.";
    }
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const question = input.value.trim();

    if (!question) return;

    if (!currentDocumentId) {
        addAIMessage("Please upload a document or add a website first.");
        return;
    }

    addUserMessage(question);
    input.value = "";

    const sendButton = document.getElementById("sendChatBtn");
    sendButton.disabled = true;
    document.getElementById("typingIndicator").classList.remove("hidden");

    try {
        const endpoint = isGuestMode ? `${RAG_URL}/api/rag/guest-ask` : `${RAG_URL}/api/rag/ask`;
        const headers = {"Content-Type":"application/json"};

        if (!isGuestMode) headers.Authorization = `Bearer ${localStorage.getItem("quelyToken")}`;

        const response = await fetch(endpoint, {
            method: "POST",
            headers,
            body: JSON.stringify({
                documentId: currentDocumentId,
                documentName: currentDocumentName,
                question,
                authenticated: !isGuestMode
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

    if (sources && sources.length) {
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

function handleChatKey(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function scrollChatToBottom() {
    const container = document.getElementById("chatMessages");
    container.scrollTop = container.scrollHeight;
}

async function loadChatHistory(restoreLatestChat = false) {
    const token = localStorage.getItem("quelyToken");
    if (!token) return;

    try {
        const response = await fetch(`${API_URL}/api/chats/history`, {
            method: "GET",
            headers: {"Authorization": `Bearer ${token}`}
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
                month:"short",
                day:"numeric",
                year:"numeric"
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

        if (restoreLatestChat && data.chats.length) openChatFromHistory(data.chats[0]);
    } catch (error) {
        console.error("Unable to load chat history:", error);
    }
}

async function openChatFromHistory(chat) {
    isGuestMode = false;
    currentDocumentId = chat.documentId || chat.documentPath;
    currentDocumentName = chat.documentName || "Document";

    try {
        const token = localStorage.getItem("quelyToken");

        await fetch(`${API_URL}/api/chats/open/${chat._id}`, {
            method: "POST",
            headers: {"Authorization": `Bearer ${token}`}
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

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
    const token = localStorage.getItem("quelyToken");
    const userData = localStorage.getItem("quelyUser");

    if (token && userData) {
        try {
            openDashboard(JSON.parse(userData), true);
        } catch (error) {
            console.error("Invalid saved user:", error);
            localStorage.removeItem("quelyToken");
            localStorage.removeItem("quelyUser");
        }
    }
});


function toggleMobileSidebar() {
    const sidebar = document.getElementById("dashboardSidebar");
    const overlay = document.getElementById("sidebarOverlay");
    if (!sidebar || !overlay) return;
    sidebar.classList.toggle("open");
    overlay.classList.toggle("active");
}

function closeMobileSidebar() {
    const sidebar = document.getElementById("dashboardSidebar");
    const overlay = document.getElementById("sidebarOverlay");
    if (!sidebar || !overlay) return;
    sidebar.classList.remove("open");
    overlay.classList.remove("active");
}