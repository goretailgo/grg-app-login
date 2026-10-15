import { Component, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const POLL_MS = 2000;

export class GrgQrSessionField extends Component {
    static template = "grg_app_login_qr.QrSessionField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, status: {}, secondsLeft: 0 });
        this.pollTimer = null;
        this.tickTimer = null;
        this.sessionId = this.props.record.data[this.props.name];

        onWillStart(() => this.refresh());
        onMounted(() => this.startTimers());
        onWillUpdateProps(async (nextProps) => {
            const nextId = nextProps.record.data[nextProps.name];
            if (nextId !== this.sessionId) {
                this.sessionId = nextId;
                this.state.loading = true;
                await this.refresh();
                this.startTimers();
            }
        });
        onWillUnmount(() => this.stopTimers());
    }

    get progress() {
        const total = this.state.status.validity || 30;
        return Math.max(0, Math.min(100, (100 * this.state.secondsLeft) / total));
    }

    startTimers() {
        this.stopTimers();
        this.tickTimer = setInterval(() => {
            if (this.state.status.state === "pending" && this.state.secondsLeft > 0) {
                this.state.secondsLeft--;
            }
        }, 1000);
        this.pollTimer = setInterval(() => this.refresh(), POLL_MS);
    }

    stopTimers() {
        clearInterval(this.tickTimer);
        clearInterval(this.pollTimer);
        this.tickTimer = this.pollTimer = null;
    }

    async refresh() {
        if (!this.sessionId) {
            this.state.loading = false;
            return;
        }
        try {
            const status = await this.orm.call(
                "grg.app.login.qr.session", "get_status", [[this.sessionId]]
            );
            this.state.status = status;
            this.state.secondsLeft = status.seconds_left;
            this.state.loading = false;
            if (status.state !== "pending") {
                this.stopTimers();
            }
        } catch {
            this.stopTimers();
        }
    }
}

registry.category("fields").add("grg_qr_session", {
    component: GrgQrSessionField,
    supportedTypes: ["integer"],
});
