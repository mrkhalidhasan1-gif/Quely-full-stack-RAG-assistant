const express = require("express");
const Chat = require("../models/Chat");
const authMiddleware = require("../middleware/auth");

const router = express.Router();

router.get("/history", authMiddleware, async (req, res) => {
    try {
        const chats = await Chat.find({ userId: req.userId })
            .sort({ updatedAt: -1 })
            .select("title documentName documentPath messages createdAt updatedAt");

        res.json({ chats });
    } catch (error) {
        console.error("History fetch error:", error);
        res.status(500).json({ message: "Unable to load chat history." });
    }
});

router.post("/open/:chatId", authMiddleware, async (req, res) => {
    try {
        const chat = await Chat.findOneAndUpdate(
            { _id: req.params.chatId, userId: req.userId },
            { $set: { updatedAt: new Date() } },
            { new: true }
        );

        if (!chat) return res.status(404).json({ message: "Chat not found." });

        res.json({ message: "Chat opened.", chat });
    } catch (error) {
        console.error("Chat open error:", error);
        res.status(500).json({ message: "Unable to update chat." });
    }
});

module.exports = router;