# Argo CD
## GitHub SSO
Argo CD provides a basic implementation for user management with the expectation that most organizations will set up Single Sign-On (SSO). You will use GitHub as the SSO provider by creating a GitHub App. 

In it's default configuration, this will allow anyone with a GitHub account to log into your Argo CD instance and assume the `readonly` role from [the default RBAC policy](https://github.com/argoproj/argo-cd/blob/2fe132eec746d293dd5878fc25f4252dd4a0be48/assets/builtin-policy.csv#L9) in Argo CD.

1. [Create a new GitHub App](https://github.com/settings/apps/new).
    - Set <hlt>GitHub App name</hlt> to `argocd-sso-<username>`, replacing `<username>` with your GitHub username. 
      
      :::caution
      
      GitHub App names are globally unique, so including the `<username>` is essential.

      :::

    - Set <hlt>Homepage URL</hlt> to `https://<instance-id>.cd.akuity.cloud/`, replacing `<instance-id>` with the ID for the Argo CD instance on the Akuity Platform.

      <!-- Use code block to make URL easy to copy. -->
      ```
      https://<instance-id>.cd.akuity.cloud/
      ```

      ![akuity-argo-cd-instance-id](./akuity-argo-cd-instance-id.png)
    
    - Set <hlt>Authorization callback URL</hlt> to `https://<instance-id>.cd.akuity.cloud/api/dex/callback`, replacing `<instance-id>` with the ID for the Argo CD instance on the Akuity Platform.

      ```
      https://<instance-id>.cd.akuity.cloud/api/dex/callback
      ```
    
    - Under the "Webhook" section, **deselect** the <hlt>Active</hlt> option.

    - Under the "Permissions" section, expand the <hlt>Account permissions</hlt> then set <hlt>Email addresses</hlt> to `Read-only` access level.

      :::info

      The `Read-only` access for <hlt>Email addresses</hlt> is required for GitHub users that have their email address set to private.

      :::

    - Click <hlt>Create GitHub App</hlt>.

2. In the settings for the GitHub App, under "Client secrets", click <hlt>Generate a new client secret</hlt>.

3. Back on the Akuity Platform, in the <hlt>Settings</hlt> for the Argo CD instance, go to <hlt>SSO Configuration</hlt> > <hlt>Configuration</hlt> and click <hlt>Add new connector</hlt>
    <!-- `https://akuity.cloud/<organization-name>/argocd/<instance-name>?tab=settings&section=sso` -->
    
    - Set <hlt>Type</hlt> to `github`.
    
    - Under <hlt>Client Secret</hlt>, set <hlt>$GITHUB-CLIENT-SECRET</hlt> to the client secret genereted in the previous step.
    
    - Set <hlt>Client ID</hlt> to the value to the "Client ID" from the GitHub App.
    
    - Click <hlt>Add</hlt>.
    
    - Click <hlt>Save</hlt>.

4. Configure the RBAC policies.
    <!-- `https://akuity.cloud/<organization-name>/argocd/<instance-name>?tab=settings&section=rbac` -->

    - In the <hlt>Settings</hlt> for the Argo CD instance, go to <hlt>RBAC</hlt>.

    - Under <hlt>OIDC Scopes</hlt>, click <hlt>Add Scope</hlt> and enter `email`.

    - Under <hlt>Policy</hlt>, add this line to make yourself an `admin`. Replace `<email>` with your GitHub public email address found [under `settings/profile`](https://github.com/settings/profile).
    
      ```
      g, <email>, role:admin
      ```

    - Click <hlt>Save</hlt>.

5. After the instance has finished progressing, log into Argo CD using GitHub SSO.

    - From the Akuity Platform dashboard for the Argo CD instance, click the `<instance-id>.cd.akuity.cloud` link.

      ![Akuity Argo CD instance link.](./akuity-argo-cd-link.png)

    - Click <hlt>LOG IN VIA GITHUB</hlt>.
    
    - Click <hlt>Authorize argocd-sso-<username\></hlt>.

You are now logged into Argo CD by authenticating with your GitHub account. By setting the OICD scope to  `email` and adding a policy to assign your email to the `admin` role, you can perform any function within Argo CD.


:::tip
If you encounter a `Not found` error page at this step, this may indicate that the GitHub app was configured incorrectly. Confirm that the <hlt>Homepage URL</hlt> and <hlt>Authorization callback URL</hlt> are correct.
:::