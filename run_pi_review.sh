#!/bin/bash
cd /tmp/hermes-pr/file-catalog-146
pi --mode json -p "/skill:github-pr-review Perform a review of PR #146" < /dev/null > pi_review.log 2>&1
echo $? > pi_review.exit
