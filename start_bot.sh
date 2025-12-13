#!/bin/bash
# External supervisor script that restarts the trading bot if it crashes or gets killed
# This handles OOM kills where the Python process dies without catching exceptions

LOG_FILE="logs/supervisor.log"
MAX_RESTARTS=100
RESTART_DELAY=10
restart_count=0

mkdir -p logs

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_message "========================================"
log_message "SUPERVISOR STARTING"
log_message "Max restarts: $MAX_RESTARTS"
log_message "========================================"

while [ $restart_count -lt $MAX_RESTARTS ]; do
    log_message "Starting trading bot (attempt $((restart_count + 1)))"
    
    # Run the bot and capture exit code
    python run.py
    exit_code=$?
    
    log_message "Bot exited with code: $exit_code"
    
    # Check if it was a clean shutdown (exit code 0 or keyboard interrupt)
    if [ $exit_code -eq 0 ]; then
        log_message "Clean shutdown - not restarting"
        break
    fi
    
    # Check for OOM kill (exit code 137 = SIGKILL)
    if [ $exit_code -eq 137 ]; then
        log_message "DETECTED OOM KILL (SIGKILL) - process was killed by OS"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OOM KILL DETECTED - exit code 137" >> logs/process_crash.log
    fi
    
    restart_count=$((restart_count + 1))
    
    # Exponential backoff (10s, 15s, 22s, ... up to 5 min)
    if [ $RESTART_DELAY -lt 300 ]; then
        RESTART_DELAY=$((RESTART_DELAY * 3 / 2))
    fi
    
    log_message "Restarting in ${RESTART_DELAY}s... (restart #$restart_count)"
    sleep $RESTART_DELAY
done

if [ $restart_count -ge $MAX_RESTARTS ]; then
    log_message "FATAL: Exceeded $MAX_RESTARTS restart attempts"
fi

log_message "Supervisor exiting"
