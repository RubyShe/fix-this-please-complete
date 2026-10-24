<current>
<request>
You are working on an issue in the 'BerryCloud/xapi-java' repository.



<repository_context>
I've cloned the repository in the directory /home/runner/work/xapi-java/xapi-java (not in /tmp/inputs). Always use absolute paths when referring to files in the repository.
</repository_context>

<current_datetime>2025-11-19T00:50:11.723Z</current_datetime>

Consider the following problem statement:
<problem_statement>
Modify .github/workflows/copilot-setup-steps.yml to change the Build with Maven step so the Copilot setup workflow installs dependencies without running Checkstyle. Current line:

run: ./mvnw -B clean verify -DskipTests --file pom.xml

Required change:
Replace with:

run: ./mvnw -B clean install -DskipTests -Dcheckstyle.skip=true --file pom.xml

Constraints:
- Only update the single workflow file .github/workflows/copilot-setup-steps.yml.
- Keep the workflow header, name, triggers, job name, permissions, and other steps unchanged.
- Commit message: "copilot-setup: use 'install' and skip Checkstyle during setup"
- Branch name: copilot/setup-install-skip-checkstyle
- PR title should be: "copilot-setup: use 'install' and skip Checkstyle during setup"

Make a one-file change and open a pull request in repository BerryCloud/xapi-java. Do not add assignees or reviewers. Include the exact updated file content in the change.

</problem_statement>

Implement the necessary changes to the repository so that the requirements specified in the <problem_statement> are met.



Ensure that you lint, build and test early and iteratively to validate each code change thoroughly.


</request>
</current>
