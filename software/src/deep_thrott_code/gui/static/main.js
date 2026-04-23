(() => {
	function setSystemMessage(text) {
		const el = document.getElementById('systemMessage');
		if (el) el.textContent = text;
	}

	const MAX_POINTS = 300;
	const historyBySensor = new Map(); // sensorName -> {t: number[], v: number[], units: string}
	let knownSensorNames = [];

	const plotWidgets = [
		{ canvasId: 'daqPlot1', selectId: 'daqSelect1', defaultSensor: 'thrust' },
		{ canvasId: 'daqPlot2', selectId: 'daqSelect2', defaultSensor: 'tank_temp' },
		{ canvasId: 'daqPlot3', selectId: 'daqSelect3', defaultSensor: 'injector_pressure' },
		{ canvasId: 'daqPlot4', selectId: 'daqSelect4', defaultSensor: 'chamber_pressure' },
		{ canvasId: 'daqPlot5', selectId: 'daqSelect5', defaultSensor: '' },
		{ canvasId: 'daqPlot6', selectId: 'daqSelect6', defaultSensor: '' },
	];

	const bindings = [
		{ sensorName: 'chamber_pressure', elementId: 'sensor-PFF-PT' },
		{ sensorName: 'injector_pressure', elementId: 'sensor-FT-PT' },
		{ sensorName: 'chamber_pressure', elementId: 'sensor-FM-PT' },
		{ sensorName: 'injector_pressure', elementId: 'sensor-FF-PT' },
	];

	function setPressureBox(el, valuePsi) {
		if (!el) return;
		const rounded = Math.round(valuePsi);
		el.textContent = `${rounded} PSI`;

		const thresholdStr = el.dataset.greenThresholdPsi;
		const thresholdPsi = thresholdStr ? Number(thresholdStr) : NaN;
		const isGood = Number.isFinite(thresholdPsi) ? valuePsi <= thresholdPsi : false;
		el.classList.toggle('good', isGood);
	}

	function getDaqStageVisible() {
		const stage = document.getElementById('daqStage');
		return !!stage && !stage.classList.contains('hidden');
	}

	function resizeCanvasToDisplaySize(canvas) {
		if (!canvas) return false;
		const dpr = window.devicePixelRatio || 1;
		const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
		const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
		if (canvas.width !== width || canvas.height !== height) {
			canvas.width = width;
			canvas.height = height;
			return true;
		}
		return false;
	}

	function setSelectOptions(selectEl, sensorNames) {
		if (!selectEl) return;

		const current = selectEl.value;
		selectEl.innerHTML = '';

		const emptyOpt = document.createElement('option');
		emptyOpt.value = '';
		emptyOpt.textContent = '— select signal —';
		selectEl.appendChild(emptyOpt);

		for (const name of sensorNames) {
			const opt = document.createElement('option');
			opt.value = name;
			opt.textContent = name;
			selectEl.appendChild(opt);
		}

		if (sensorNames.includes(current)) {
			selectEl.value = current;
		}
	}

	function updateAllSelectOptionsIfNeeded(sensorNames) {
		const same = sensorNames.length === knownSensorNames.length && sensorNames.every((v, i) => v === knownSensorNames[i]);
		if (same) return;
		knownSensorNames = sensorNames;
		for (const w of plotWidgets) {
			const selectEl = document.getElementById(w.selectId);
			setSelectOptions(selectEl, knownSensorNames);
			if (w.defaultSensor && selectEl && (!selectEl.value || selectEl.value === '')) {
				if (knownSensorNames.includes(w.defaultSensor)) selectEl.value = w.defaultSensor;
			}
		}
	}

	function ingestPacketForPlots(packet) {
		if (!packet || typeof packet !== 'object') return;
		const states = packet.states;
		if (!states || typeof states !== 'object') return;

		const tWall = typeof packet.t_wall === 'number' ? packet.t_wall : Date.now() / 1000;
		const sensorNames = Object.keys(states).sort();
		updateAllSelectOptionsIfNeeded(sensorNames);

		for (const name of sensorNames) {
			const state = states[name];
			if (!state || typeof state !== 'object') continue;
			const value = state.value;
			if (typeof value !== 'number') continue;
			const units = typeof state.units === 'string' ? state.units : '';

			let rec = historyBySensor.get(name);
			if (!rec) {
				rec = { t: [], v: [], units };
				historyBySensor.set(name, rec);
			}
			if (units) rec.units = units;

			rec.t.push(tWall);
			rec.v.push(value);
			if (rec.t.length > MAX_POINTS) {
				rec.t.splice(0, rec.t.length - MAX_POINTS);
				rec.v.splice(0, rec.v.length - MAX_POINTS);
			}
		}
	}

	function drawPlot(canvas, sensorName) {
		if (!canvas) return;
		resizeCanvasToDisplaySize(canvas);
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const w = canvas.width;
		const h = canvas.height;
		ctx.clearRect(0, 0, w, h);

		// Background
		ctx.fillStyle = '#ffffff';
		ctx.fillRect(0, 0, w, h);
		ctx.strokeStyle = '#666666';
		ctx.lineWidth = 2;
		ctx.strokeRect(0, 0, w, h);

		if (!sensorName) {
			ctx.fillStyle = '#111111';
			ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
			ctx.fillText('Select a signal', Math.floor(w * 0.05), Math.floor(h * 0.18));
			return;
		}

		const rec = historyBySensor.get(sensorName);
		if (!rec || rec.t.length < 2) {
			ctx.fillStyle = '#111111';
			ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
			ctx.fillText(`${sensorName}: waiting for data...`, Math.floor(w * 0.05), Math.floor(h * 0.18));
			return;
		}

		const pad = Math.max(10, Math.floor(Math.min(w, h) * 0.08));
		const left = pad;
		const right = w - pad;
		const top = pad;
		const bottom = h - pad;

		let minV = Infinity;
		let maxV = -Infinity;
		for (const v of rec.v) {
			if (v < minV) minV = v;
			if (v > maxV) maxV = v;
		}
		if (!Number.isFinite(minV) || !Number.isFinite(maxV)) return;
		if (minV === maxV) {
			const bump = minV === 0 ? 1 : Math.abs(minV) * 0.1;
			minV -= bump;
			maxV += bump;
		}

		const t0 = rec.t[0];
		const t1 = rec.t[rec.t.length - 1];
		const dt = t1 - t0 || 1;

		// Axes
		ctx.strokeStyle = '#666666';
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(left, top);
		ctx.lineTo(left, bottom);
		ctx.lineTo(right, bottom);
		ctx.stroke();

		// Line
		ctx.strokeStyle = '#2957ff';
		ctx.lineWidth = 2;
		ctx.beginPath();
		for (let i = 0; i < rec.t.length; i++) {
			const x = left + ((rec.t[i] - t0) / dt) * (right - left);
			const yNorm = (rec.v[i] - minV) / (maxV - minV);
			const y = bottom - yNorm * (bottom - top);
			if (i === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.stroke();

		// Title / latest value
		const latestV = rec.v[rec.v.length - 1];
		const units = rec.units ? ` ${rec.units}` : '';
		ctx.fillStyle = '#111111';
		ctx.font = `${Math.max(12, Math.floor(h * 0.08))}px Arial`;
		ctx.fillText(`${sensorName}: ${latestV.toFixed(2)}${units}`, left, Math.max(top - 6, Math.floor(h * 0.12)));
	}

	function renderAllPlots() {
		if (!getDaqStageVisible()) return;
		for (const w of plotWidgets) {
			const canvas = document.getElementById(w.canvasId);
			const selectEl = document.getElementById(w.selectId);
			const sensorName = selectEl ? selectEl.value : '';
			drawPlot(canvas, sensorName);
		}
	}

	function initDaqControls() {
		for (const w of plotWidgets) {
			const selectEl = document.getElementById(w.selectId);
			if (!selectEl) continue;
			if (!selectEl.querySelector('option')) {
				const opt = document.createElement('option');
				opt.value = '';
				opt.textContent = 'Waiting for data...';
				selectEl.appendChild(opt);
			}
			selectEl.addEventListener('change', () => renderAllPlots());
		}

		document.querySelectorAll('.tab[data-tab="daq"]').forEach((t) => {
			t.addEventListener('click', () => {
				// Defer to allow DOM to update visibility.
				setTimeout(() => renderAllPlots(), 0);
			});
		});

		window.addEventListener('resize', () => renderAllPlots());
	}

	function applyPacket(packet) {
		if (!packet || typeof packet !== 'object') return;
		const states = packet.states;
		if (!states || typeof states !== 'object') return;

		for (const { sensorName, elementId } of bindings) {
			const state = states[sensorName];
			if (!state || typeof state !== 'object') continue;
			const value = state.value;
			if (typeof value !== 'number') continue;
			const el = document.getElementById(elementId);
			setPressureBox(el, value);
		}

		ingestPacketForPlots(packet);
		renderAllPlots();
	}

	function connectSocket() {
		if (typeof window.io !== 'function') {
			console.error('Socket.IO client not loaded (window.io missing).');
			setSystemMessage('System message: Socket.IO client failed to load (check internet/CDN).');
			return;
		}

		const socket = window.io();
		socket.on('connect', () => {
			setSystemMessage('System message: Connected to DAQ stream.');
		});
		socket.on('disconnect', () => {
			setSystemMessage('System message: Disconnected from DAQ stream.');
		});
		socket.on('connect_error', (err) => {
			console.error('Socket connect_error:', err);
			setSystemMessage('System message: Socket connect error (see console).');
		});
		socket.on('daq_packet', (pkt) => {
			applyPacket(pkt);
		});
	}

	window.addEventListener('load', () => {
		initDaqControls();
		connectSocket();
	});
})();
