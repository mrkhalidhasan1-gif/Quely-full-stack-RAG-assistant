const mongoose = require("mongoose");

const messageSchema = new mongoose.Schema(
    {
        role: { type: String, enum: ["user", "assistant"], required: true },
        content: { type: String, required: true },
        sources: { type: Array, default: [] }
    },
    { _id: false }
);

const chatSchema = new mongoose.Schema(
    {
        userId: { type: mongoose.Schema.Types.ObjectId, ref: "User", required: true, index: true },
        title: { type: String, required: true },
        documentName: { type: String, default: "" },
        documentPath: { type: String, default: "" },
        messages: { type: [messageSchema], default: [] }
    },
    { timestamps: true }
);

module.exports = mongoose.model("Chat", chatSchema);