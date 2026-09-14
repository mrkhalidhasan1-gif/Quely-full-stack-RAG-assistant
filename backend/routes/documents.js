const express = require("express");
const multer = require("multer");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const crypto = require("crypto");

const authMiddleware = require("../middleware/auth");
const Chat = require("../models/Chat");

const router = express.Router();

const uploadDir = "/tmp/quely-uploads/";

if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

const upload = multer({ dest: uploadDir });


// =========================
// PREPARE UPLOADED FILE
// =========================

function prepareUploadedFile(file) {
    const extension = path.extname(file.originalname).toLowerCase();
    if (!extension) return file;

    const newPath = file.path + extension;
    fs.renameSync(file.path, newPath);
    file.path = newPath;

    return file;
}


// =========================
// RUN RAG PROCESS
// =========================

function processDocument(filePath, callback) {
    const pythonScript = path.join(__dirname, "..", "..", "rag", "rag.py");

    const pythonProcess = spawn(
        "python3",
        [pythonScript, filePath, "--process-only"],
        {
            cwd: path.join(__dirname, "..", "..", "rag"),
            detached: false
        }
    );

    pythonProcess.stdout.on("data", data => {
        console.log("RAG stdout:", data.toString());
    });

    pythonProcess.stderr.on("data", data => {
        console.error("RAG stderr:", data.toString());
    });

    pythonProcess.on("close", code => {
        console.log(`RAG process exited with code ${code}`);
        callback(code);
    });
}


// =========================
// RUN ASK
// =========================

function askRag(documentPath, question, callback) {
    const pythonProcess = spawn(
        "python3",
        ["../../rag/ask.py", documentPath, question],
        { cwd: __dirname }
    );

    let output = "";
    let errorOutput = "";

    pythonProcess.stdout.on("data", data => {
        output += data.toString();
    });

    pythonProcess.stderr.on("data", data => {
        errorOutput += data.toString();
    });

    pythonProcess.on("close", code => {
        callback(code, output, errorOutput);
    });
}


// =========================
// CREATE WEBSITE DOCUMENT
// =========================

async function createWebsiteDocument(url) {
    let parsedUrl;

    try {
        parsedUrl = new URL(url);
    } catch {
        throw new Error("Invalid website URL");
    }

    if (!["http:", "https:"].includes(parsedUrl.protocol)) {
        throw new Error("Only HTTP and HTTPS URLs are supported");
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    try {
        const response = await fetch(url, {
            signal: controller.signal,
            headers: { "User-Agent": "Quely/1.0" }
        });

        if (!response.ok) {
            throw new Error(`Unable to fetch website: ${response.status}`);
        }

        const html = await response.text();

        const text = html
            .replace(/<script[\s\S]*?<\/script>/gi, " ")
            .replace(/<style[\s\S]*?<\/style>/gi, " ")
            .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
            .replace(/<[^>]+>/g, " ")
            .replace(/&nbsp;/gi, " ")
            .replace(/&amp;/gi, "&")
            .replace(/&lt;/gi, "<")
            .replace(/&gt;/gi, ">")
            .replace(/&quot;/gi, '"')
            .replace(/&#39;/gi, "'")
            .replace(/\s+/g, " ")
            .trim();

        if (!text) throw new Error("No readable content found on website");

        const id = crypto.randomUUID();
        const filePath = path.join(uploadDir, `website-${id}.txt`);

        fs.writeFileSync(filePath, text, "utf8");

        return {
            path: filePath,
            name: parsedUrl.hostname
        };
    } finally {
        clearTimeout(timeout);
    }
}


// =========================
// AUTHENTICATED UPLOAD
// =========================

router.post("/upload", authMiddleware, upload.single("document"), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ message: "Please upload a document" });
    }

    try {
        prepareUploadedFile(req.file);
    } catch (error) {
        console.error("File preparation error:", error);
        return res.status(500).json({ message: "Unable to prepare document." });
    }

    processDocument(req.file.path, code => {
        if (code !== 0) {
            return res.status(500).json({ message: "Unable to process document." });
        }

        return res.json({
            message: "Document processed successfully.",
            file: req.file
        });
    });
});


// =========================
// GUEST UPLOAD
// =========================

router.post("/guest-upload", upload.single("document"), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ message: "Please upload a document" });
    }

    try {
        prepareUploadedFile(req.file);
    } catch (error) {
        console.error("File preparation error:", error);
        return res.status(500).json({ message: "Unable to prepare document." });
    }

    processDocument(req.file.path, code => {
        if (code !== 0) {
            return res.status(500).json({ message: "Unable to process document." });
        }

        return res.json({
            message: "Document processed successfully.",
            file: req.file
        });
    });
});


// =========================
// AUTHENTICATED WEBSITE
// =========================

router.post("/website", authMiddleware, async (req, res) => {
    const { url } = req.body;

    if (!url) {
        return res.status(400).json({ message: "Website URL is required." });
    }

    try {
        const website = await createWebsiteDocument(url);

        processDocument(website.path, code => {
            if (code !== 0) {
                return res.status(500).json({ message: "Unable to process website." });
            }

            return res.json({
                message: "Website processed successfully.",
                documentPath: website.path,
                documentName: website.name
            });
        });
    } catch (error) {
        console.error("Website processing error:", error);

        return res.status(400).json({
            message: error.message || "Unable to process website."
        });
    }
});


// =========================
// GUEST WEBSITE
// =========================

router.post("/guest-website", async (req, res) => {
    const { url } = req.body;

    if (!url) {
        return res.status(400).json({ message: "Website URL is required." });
    }

    try {
        const website = await createWebsiteDocument(url);

        processDocument(website.path, code => {
            if (code !== 0) {
                return res.status(500).json({ message: "Unable to process website." });
            }

            return res.json({
                message: "Website processed successfully.",
                documentPath: website.path,
                documentName: website.name
            });
        });
    } catch (error) {
        console.error("Guest website processing error:", error);

        return res.status(400).json({
            message: error.message || "Unable to process website."
        });
    }
});


// =========================
// AUTHENTICATED ASK
// =========================

router.post("/ask", authMiddleware, async (req, res) => {
    const { documentPath, documentName, question } = req.body;

    if (!documentPath || !question) {
        return res.status(400).json({
            message: "Document and question are required."
        });
    }

    askRag(documentPath, question, async (code, output, errorOutput) => {
        if (code !== 0) {
            console.log("RAG Ask Error:", errorOutput);

            return res.status(500).json({
                message: "Unable to generate answer."
            });
        }

        try {
            const marker = "QUELY_RESULT:";
            const resultLine = output.split("\n").find(line => line.startsWith(marker));

            if (!resultLine) throw new Error("RAG result not found");

            const result = JSON.parse(resultLine.substring(marker.length));

            let chat = await Chat.findOne({
                userId: req.userId,
                documentPath
            });

            if (!chat) {
                chat = await Chat.create({
                    userId: req.userId,
                    title: question.substring(0, 60),
                    documentName: documentName || "",
                    documentPath,
                    messages: [
                        { role: "user", content: question },
                        {
                            role: "assistant",
                            content: result.answer,
                            sources: result.sources || []
                        }
                    ]
                });
            } else {
                chat.messages.push({
                    role: "user",
                    content: question
                });

                chat.messages.push({
                    role: "assistant",
                    content: result.answer,
                    sources: result.sources || []
                });

                await chat.save();
            }

            return res.json(result);
        } catch (error) {
            console.log("RAG response parse error:", error);

            return res.status(500).json({
                message: "Invalid response from RAG."
            });
        }
    });
});


// =========================
// GUEST ASK
// =========================

router.post("/guest-ask", async (req, res) => {
    const { documentPath, question } = req.body;

    if (!documentPath || !question) {
        return res.status(400).json({
            message: "Document and question are required."
        });
    }

    askRag(documentPath, question, (code, output, errorOutput) => {
        if (code !== 0) {
            console.log("Guest RAG Ask Error:", errorOutput);

            return res.status(500).json({
                message: "Unable to generate answer."
            });
        }

        try {
            const marker = "QUELY_RESULT:";
            const resultLine = output.split("\n").find(line => line.startsWith(marker));

            if (!resultLine) throw new Error("RAG result not found");

            const result = JSON.parse(resultLine.substring(marker.length));

            return res.json(result);
        } catch (error) {
            console.log("Guest RAG response parse error:", error);

            return res.status(500).json({
                message: "Invalid response from RAG."
            });
        }
    });
});


module.exports = router;