# ==========================================================
# Systemd Deployment
# ==========================================================

# Copy Service Files
sudo cp systemd/*.service /etc/systemd/system/

# Copy Timer Files
sudo cp systemd/*.timer /etc/systemd/system/

# Reload Systemd
sudo systemctl daemon-reload

# ==========================================================
# Enable Timers
# ==========================================================

sudo systemctl enable market-data-start.timer
sudo systemctl enable market-data-stop.timer
sudo systemctl enable backup.timer
sudo systemctl enable health.timer
sudo systemctl enable log-cleanup.timer

# ==========================================================
# Start Timers
# ==========================================================

sudo systemctl start market-data-start.timer
sudo systemctl start market-data-stop.timer
sudo systemctl start backup.timer
sudo systemctl start health.timer
sudo systemctl start log-cleanup.timer

# ==========================================================
# Verify Timers
# ==========================================================

systemctl status \
market-data-start.timer \
market-data-stop.timer \
backup.timer \
health.timer \
log-cleanup.timer \
--no-pager

# ==========================================================
# Verify Services
# ==========================================================

systemctl status \
market-data-collector.service \
backup.service \
health.service \
log-cleanup.service \
--no-pager

# ==========================================================
# Verify Next Scheduled Runs
# ==========================================================

systemctl list-timers --all | grep -E "market-data|backup|health|log-cleanup"

# ==========================================================
# Verify Enabled State
# ==========================================================

systemctl is-enabled \
market-data-start.timer \
market-data-stop.timer \
backup.timer \
health.timer \
log-cleanup.timer