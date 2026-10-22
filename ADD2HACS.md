To include your custom integration in the Home Assistant Community Store (HACS) default list, you must submit a Pull Request (PR) to the official HACS Default Repository on GitHub.
Note that only the owner or a major contributor of the repository can submit this request.

Phase 1: Verify Pre-Requisites

Before submitting, ensure your integration meets all repository requirements:
1. GitHub Setup: The repository must be public, have a descriptive repository summary, a comprehensive README.md, and active GitHub Releases (with proper tags like v1.0.0).
2. File Structure: You must have a hacs.json file in your repository root and a properly configured manifest.json inside your integration's directory (custom_components/your_integration/).
3. Brand Assets: You need to have submitted your logo/icon to the home-assistant/brands repository so that your domain is recognized by the ecosystem.

Phase 2: Submit to the Default List

Once your repository is ready and passes automated validations, follow these steps to add it to the storefront:
1. Fork the Repository: Go to hacs/default on GitHub and fork it to your personal GitHub account.
2. Create a Branch: Create a new branch on your fork (do not use main or master).
3. Edit the JSON File: Navigate to the integrations.json file. Add your integration entry, ensuring it is alphabetically sorted by domain:json
{
  "domain": "your_integration_domain",
  "repository": "your_github_username/your_repository_name"
}
Usa el código con precaución.
4. Open a Pull Request: Create a Pull Request from your new branch to the hacs/default repository.
5. Complete the Template: Fill out the PR template thoroughly. Automated checks will run (hassfest validation, HACS validation, etc.) to ensure your integration loads correctly.
Once the automated tests pass and the maintainers review the PR, your integration will be merged and will appear natively in the HACS/Marketplace store for all users.
