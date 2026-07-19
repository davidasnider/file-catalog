#!/bin/bash
cd /tmp/hermes-pr/file-catalog-146
pi --mode json -p "/skill:fix-comments Fix the unresolved comments on this PR. Refer to .review_context.txt for recent commits and discussion history to avoid nitpick loops." < /dev/null > pi_run.log 2>&1
echo $? > pi_run.exit
