class Ingredient extends HTMLElement {
    static observedAttributes = ["size"];
    constructor() {
        super();
    }

    attributeChangedCallback(name, oldValue, newValue) {
        console.log(
            `Attribute ${name} has changed from ${oldValue} to ${newValue}.`,
        );
    }


    connectedCallback() {
        this.innerHTML = `<div>
        Ingredient!
        </div>
        
    `
    }
}
customElements.define('ingredient', Ingredient);