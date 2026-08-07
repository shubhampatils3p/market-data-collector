# Systemd Deployment

## Copy files

sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/

## Reload

sudo systemctl daemon-reload

## Enable

sudo systemctl enable market-data-start.timer
sudo systemctl enable market-data-stop.timer
sudo systemctl enable backup.timer
sudo systemctl enable log-cleanup.timer

## Start

sudo systemctl start market-data-start.timer
sudo systemctl start market-data-stop.timer
sudo systemctl start backup.timer
sudo systemctl start log-cleanup.timer