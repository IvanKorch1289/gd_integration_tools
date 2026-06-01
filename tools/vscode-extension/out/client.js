"use strict";
/**
 * GD Integration Tools - LSP Client
 *
 * LSP (Language Server Protocol) client implementation for GD Integration Tools.
 * Provides:
 * - Text document synchronization
 * - Code completion
 * - Hover documentation
 * - Code lens for run step
 * - Diagnostics
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.createGdLspClient = createGdLspClient;
exports.registerGdHandlers = registerGdHandlers;
exports.extendGdClient = extendGdClient;
const node_1 = require("vscode-languageclient/node");
/**
 * Creates and configures the GD LSP Client
 */
function createGdLspClient(config) {
    const [host, port] = config.serverAddress.split(':');
    const portNum = parseInt(port || '8765', 10);
    const clientOptions = {
        documentSelector: [
            { language: 'gd-dsl' },
            { language: 'python', scheme: 'file' },
            { language: 'yaml', scheme: 'file' },
        ],
        diagnosticCollectionName: 'gd-integration-tools',
        errorHandler: {
            error: (error, message, count) => {
                console.error(`LSP Error (${count}):`, error, message);
                return { action: node_1.ErrorAction.Continue };
            },
            closed: () => {
                console.warn('LSP connection closed, attempting restart');
                return { action: node_1.CloseAction.Restart, message: 'Connection closed' };
            },
        },
    };
    const serverOptions = {
        run: {
            command: process.platform === 'win32' ? '.cmd' : 'node',
            args: [
                '${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js',
                `--port=${portNum}`,
            ],
            transport: node_1.TransportKind.ipc,
            options: {
                cwd: config.workspaceRoot,
                shell: true,
            },
        },
        debug: {
            command: process.platform === 'win32' ? 'cmd' : 'node',
            args: [
                '${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js',
                `--port=${portNum}`,
                '--inspect',
            ],
            transport: node_1.TransportKind.ipc,
            options: {
                cwd: config.workspaceRoot,
                shell: true,
                env: { NODE_OPTIONS: '--inspect' },
            },
        },
    };
    return new node_1.LanguageClient('gd-integration-tools-lsp', 'GD Integration Tools Language Server', serverOptions, clientOptions);
}
/**
 * Register GD-specific handlers with the language client
 */
function registerGdHandlers(client) {
    // Handle GD run step requests
    client.onRequest('gd/runStep', async (params) => {
        try {
            // This would typically call the GD backend
            return { success: true, output: 'Step executed successfully' };
        }
        catch (error) {
            return { success: false, error: String(error) };
        }
    });
    // Handle GD documentation requests
    client.onRequest('gd/documentation', async (params) => {
        try {
            // This would typically fetch documentation from the GD backend
            return {
                content: '<p>GD DSL Documentation</p>',
                range: undefined,
            };
        }
        catch (error) {
            return { content: `<p>Error fetching documentation: ${error}</p>` };
        }
    });
}
/**
 * Extension API for external access
 */
function extendGdClient(client) {
    // Extend the client with GD-specific capabilities
    client.onRequest('gd/capabilities', () => ({
        syntaxHighlighting: true,
        hoverDocs: true,
        runStepCodeLens: true,
        autoComplete: true,
    }));
}
//# sourceMappingURL=client.js.map