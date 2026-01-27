/**
 * Galangal Hub Dashboard JavaScript
 * Handles WebSocket connection and live updates
 */

class HubDashboard {
    constructor() {
        this.ws = null;
        this.reconnectInterval = null;
        this.statusElement = document.getElementById('connection-status');
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => this.onOpen();
            this.ws.onclose = () => this.onClose();
            this.ws.onerror = (error) => this.onError(error);
            this.ws.onmessage = (event) => this.onMessage(event);
        } catch (e) {
            console.error('WebSocket connection failed:', e);
            this.scheduleReconnect();
        }
    }

    onOpen() {
        console.log('Connected to hub');
        this.updateStatus('Connected', true);

        if (this.reconnectInterval) {
            clearInterval(this.reconnectInterval);
            this.reconnectInterval = null;
        }
    }

    onClose() {
        console.log('Disconnected from hub');
        this.updateStatus('Disconnected', false);
        this.scheduleReconnect();
    }

    onError(error) {
        console.error('WebSocket error:', error);
    }

    onMessage(event) {
        try {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'refresh':
                // Trigger HTMX refresh
                htmx.trigger(document.body, 'refresh');
                break;

            case 'agent_update':
                // Refresh agent list
                htmx.trigger('#agents', 'refresh');
                break;

            case 'attention_update':
                // Refresh needs attention section
                htmx.trigger('#needs-attention', 'refresh');
                break;

            case 'notification':
                this.showNotification(data.payload);
                break;

            default:
                console.log('Unknown message type:', data.type);
        }
    }

    updateStatus(text, connected) {
        if (!this.statusElement) return;

        this.statusElement.textContent = text;
        this.statusElement.classList.remove('text-green-400', 'text-red-400', 'text-gray-400');
        this.statusElement.classList.add(connected ? 'text-green-400' : 'text-red-400');
    }

    scheduleReconnect() {
        if (this.reconnectInterval) return;

        this.reconnectInterval = setInterval(() => {
            console.log('Attempting to reconnect...');
            this.connect();
        }, 5000);
    }

    showNotification(payload) {
        // Simple notification - could be enhanced with a toast library
        const { title, message, type } = payload;

        // Check if browser notifications are supported and permitted
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body: message });
        } else {
            console.log(`[${type}] ${title}: ${message}`);
        }
    }

    // API Actions
    async approveTask(agentId, taskName, feedback = null) {
        try {
            const response = await fetch(`/api/actions/${agentId}/${taskName}/approve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ feedback })
            });

            if (response.ok) {
                htmx.trigger(document.body, 'refresh');
                return true;
            } else {
                const error = await response.json();
                alert(`Failed to approve: ${error.detail || 'Unknown error'}`);
                return false;
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
            return false;
        }
    }

    async rejectTask(agentId, taskName, reason) {
        if (!reason) {
            reason = prompt('Rejection reason:');
            if (!reason) return false;
        }

        try {
            const response = await fetch(`/api/actions/${agentId}/${taskName}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason })
            });

            if (response.ok) {
                htmx.trigger(document.body, 'refresh');
                return true;
            } else {
                const error = await response.json();
                alert(`Failed to reject: ${error.detail || 'Unknown error'}`);
                return false;
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
            return false;
        }
    }

    async skipStage(agentId, taskName, reason = null) {
        if (!reason) {
            reason = prompt('Skip reason (optional):');
        }

        try {
            const response = await fetch(`/api/actions/${agentId}/${taskName}/skip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason })
            });

            if (response.ok) {
                htmx.trigger(document.body, 'refresh');
                return true;
            } else {
                const error = await response.json();
                alert(`Failed to skip: ${error.detail || 'Unknown error'}`);
                return false;
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
            return false;
        }
    }

    async rollbackTask(agentId, taskName, targetStage, feedback = null) {
        try {
            const response = await fetch(`/api/actions/${agentId}/${taskName}/rollback`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_stage: targetStage, feedback })
            });

            if (response.ok) {
                htmx.trigger(document.body, 'refresh');
                return true;
            } else {
                const error = await response.json();
                alert(`Failed to rollback: ${error.detail || 'Unknown error'}`);
                return false;
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
            return false;
        }
    }
}

// Initialize dashboard
const dashboard = new HubDashboard();
document.addEventListener('DOMContentLoaded', () => {
    dashboard.connect();

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
});

// Global functions for onclick handlers in templates
function approveTask(agentId, taskName) {
    dashboard.approveTask(agentId, taskName);
}

function rejectTask(agentId, taskName) {
    dashboard.rejectTask(agentId, taskName);
}

function skipStage(agentId, taskName) {
    dashboard.skipStage(agentId, taskName);
}

function rollbackTask(agentId, taskName, targetStage) {
    dashboard.rollbackTask(agentId, taskName, targetStage);
}
